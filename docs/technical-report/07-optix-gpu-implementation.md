# 07　OptiX/GPU 实现

前六章已经给出渲染器的数学、采样与几何。本章把一个典型 OptiX 应用从**构建期**到**运行期**、再到资源销毁的完整流程映射到 SpectralDock。几何上传和加速结构的细节在[第 6 章](06-geometry-visibility-and-bvh.md)，降噪与显示输出在[第 8 章](08-denoising-color-and-output.md)；本章是贯穿三章的流程总线。

## 1. 标准七步在本项目中的位置

| 标准步骤 | SpectralDock 的实现 | 时机 | 详细位置 |
|---|---|---|---|
| 准备 CUDA 几何数据 | 将 mesh 的 position、normal、UV、index 和解析 primitive 的构建输入放入设备缓冲区 | 运行期，单帧 | 第 6 章 |
| 构建 GAS / IAS 加速结构 | 每份 mesh 资源或解析对象构建 GAS，再用对象变换、GAS handle 与 `sbtOffset` 构建 IAS；两级都只在紧凑结果更小时压缩 | 运行期，单帧 | 第 6 章 |
| 编译 RayGen、Miss、Hit 等程序 | NVCC 把设备程序编译成 OptiX IR；运行时从 IR 创建 module 和 program groups | 构建期 + 运行期初始化 | 本章第 3、4 节 |
| 创建 Pipeline 和 Shader Binding Table | 先链接 pipeline；GAS/IAS 完成后再为 raygen、miss 和每个对象的两类射线打包 SBT | 运行期，单帧 | 本章第 4、6 节 |
| 调用 optixLaunch | 上传 `LaunchParams`，以 `width × height × 1` 启动二维工作网格 | 运行期，单帧 | 本章第 7、8 节 |
| 执行射线遍历、求交和自定义着色 | `optixTrace` 遍历 IAS/GAS；intersection、any-hit、closest-hit 参与命中查询，raygen 完成路径着色循环 | 运行期，设备端 | 本章第 9 节与第 6 章 |
| 使用 OptiX Denoiser 降噪 | `denoise=true` 时对线性 HDR beauty 使用 albedo/normal guide 降噪 | 运行期，可选 | 第 8 章 |

七步全部存在，但并非每一步都在同一时刻发生。NVCC 编译只属于构建期；OptiX Denoiser 是可选步骤；第 8 章中的曝光、ACES 风格曲线和 sRGB 编码则是项目自己启动的**纯 CUDA** 后处理，不属于 OptiX ray tracing pipeline。

## 2. 两条时间线：构建产物与单帧事务

构建期：

~~~mermaid
flowchart LR
    A["device_programs.cu"] -->|"nvcc --optix-ir"| B["device_programs.optixir"]
    B -->|"运行时加载"| C["OptiX module"]
    D["postprocess.cu"] -->|"CUDA 编译"| E["spectraldock_postprocess"]
    E -->|"链接"| F["spectraldock 可执行文件"]
~~~

运行期与销毁：

~~~mermaid
flowchart TD
    A["CUDA device 0、stream、OptiX context"] --> B["加载 IR；module、program groups、pipeline"]
    B --> C["纹理、材质、灯与几何上传"]
    C --> D["构建并按收益压缩 GAS，再构建并按收益压缩 IAS"]
    D --> E["SBT、输出缓冲与 LaunchParams"]
    E --> F["optixLaunch：遍历、求交、路径着色"]
    F --> G{"denoise?"}
    G -->|"是"| H["OptiX HDR Denoiser"]
    G -->|"否"| I["原始线性 HDR beauty"]
    H --> J["纯 CUDA：曝光、ACES、sRGB、RGBA8"]
    I --> J
    J --> K["D2H 下载、统计与 RenderResult"]
    K --> L["RAII 逆序销毁资源"]
~~~

当前真实顺序是**先创建 pipeline，再上传场景并构建 GAS/IAS**；pipeline 依赖程序，GAS/IAS 依赖几何，SBT 和 launch 才把两条链连接起来。当前每次 `render_optix` 都重新创建和销毁本函数拥有的 OptiX 与场景 GPU 资源，没有跨帧缓存。

![SpectralDock 的 OptiX 数据结构与程序流](figures/optix-pipeline.svg)

*图 6：这张结构图说明 IAS/GAS、SBT 与设备程序怎样相连；上面的时间线才表示实际生命周期顺序。*

## 3. 构建期：把设备程序编译为 OptiX IR

`src/device_programs.cu` 中包含 raygen、miss、hit 和自定义 intersection 入口。它不作为普通 CUDA 对象文件链接，而由 NVCC 的 `--optix-ir` 模式生成 `device_programs.optixir`。相反，`src/postprocess.cu` 编译为普通 CUDA 静态库，稍后以 kernel launch 执行；这两条构建链必须区分。

<!-- source-snippet id="optix-ir-build-command" path="CMakeLists.txt" anchor="--optix-ir --std=c++17 --use_fast_math -lineinfo" -->
```cmake
  set(OPTIX_IR "${CMAKE_CURRENT_BINARY_DIR}/device_programs.optixir")
  add_custom_command(
    OUTPUT "${OPTIX_IR}"
    COMMAND "${CMAKE_CUDA_COMPILER}"
      --optix-ir --std=c++17 --use_fast_math -lineinfo
      -I"${CMAKE_CURRENT_SOURCE_DIR}/include"
      -I"${OPTIX_INCLUDE_DIR}"
      "${CMAKE_CURRENT_SOURCE_DIR}/src/device_programs.cu"
      -o "${OPTIX_IR}"
    DEPENDS
      src/device_programs.cu
      include/spectraldock/device_types.h
    VERBATIM)
  add_custom_target(spectraldock_device_ir DEPENDS "${OPTIX_IR}")
```

`--use_fast_math` 可提高吞吐，但部分函数采用近似实现，属于最终数值误差来源。主程序通过构建时定义的绝对路径加载 IR，因此原构建树和 IR 必须留在编译时记录的位置；v0.1 的支持范围限定为构建树或项目容器内运行，不是复制单个可执行文件即可工作的可重定位安装。

## 4. 运行期初始化：context、module、program groups 与 pipeline

### 4.1 CUDA 与 OptiX context

`render_optix` 先选择 CUDA device 0，用 `cudaFree(nullptr)` 触发 CUDA context 初始化，创建 stream，并借用当前 `CUcontext`。随后初始化 OptiX，按 `validation` 设置日志与验证级别，再创建 OptiX device context。

<!-- source-snippet id="optix-context-pipeline-setup" path="src/optix_renderer.cpp" anchor="optixDeviceContextCreate" -->
```cpp
  check_optix(optixInit(), "optixInit");

  OptixState optix;
  OptixDeviceContextOptions context_options{};
  context_options.logCallbackFunction = optix_log;
  context_options.logCallbackLevel = settings.validation ? 4 : 2;
  context_options.validationMode =
      settings.validation ? OPTIX_DEVICE_CONTEXT_VALIDATION_MODE_ALL
                          : OPTIX_DEVICE_CONTEXT_VALIDATION_MODE_OFF;
  check_optix(optixDeviceContextCreate(
                  cuda_context, &context_options, &optix.context),
              "optixDeviceContextCreate");
  const Programs programs = create_pipeline(optix);
  tracker.sample();
```

这段调用也显示了真实顺序：context 建成后立即调用 `create_pipeline`，场景上传与加速结构构建发生在它之后。

### 4.2 module 与 19 个 program groups

`create_pipeline` 读取构建期生成的 IR，创建主 module；普通 sphere 使用 OptiX 内建求交 module，水中 dielectric sphere 则使用主 module 中的自定义实心求交。当前 pipeline 有 19 个 program group：

| 类型 | 数量 | 本项目职责 |
|---|---:|---|
| ray-generation | 1 | `__raygen__pathtrace`：每个像素的 spp 与路径反弹循环 |
| miss | 2 | radiance miss 报告“未命中”，shadow miss 返回“可见” |
| hitgroup | 16 | 8 个 primitive dispatch slot × 2 类射线，组合 intersection、any-hit 和 closest-hit |

八个 dispatch slot 是 sphere、triangle、disk、cylinder、parabola、mesh、water surface 和 solid sphere。rectangle 和 sketch 在主机端变为 triangle；mesh 也使用内建三角形求交，但从 SBT 读取独立的顶点属性缓冲区。disk、cylinder、parabola、解析水面和实心 sphere 使用项目自定义 intersection；普通 sphere 与 triangle/mesh 使用 OptiX 内建求交。实心 sphere 只服务于含水场景中的 dielectric 闭合边界，原因见[第 12 章第 4 节](12-runtime-analytic-water.md#水中-dielectric-sphere-为什么使用自定义实心边界)。

### 4.3 链接浅调用栈 pipeline

程序组创建完成后才链接 pipeline。实现把 `maxTraceDepth` 设为 1，并只允许 IAS→GAS 的单层实例图：

<!-- source-snippet id="optix-shallow-pipeline-stack" path="src/optix_renderer.cpp" anchor="link.maxTraceDepth = 1;" -->
```cpp
  OptixPipelineLinkOptions link{};
  link.maxTraceDepth = 1;
  log_size = log.size();
  status = optixPipelineCreate(
      state.context, &pipeline_options, &link, state.groups.data(),
      checked_u32(state.groups.size(), "program group count"),
      log.data(), &log_size, &state.pipeline);
  check_optix(status, "optixPipelineCreate", log.data(), log_size);
  check_optix(optixPipelineSetStackSize(
                  state.pipeline, 0, 0, 4096, kMaxTraversableDepth),
              "optixPipelineSetStackSize");
  return programs;
```

`maxTraceDepth` 约束 OptiX 程序间嵌套的追踪调用深度，`optixPipelineSetStackSize` 配置栈空间与 traversable 深度；两者都不是路径反弹次数。下一条 radiance ray 不从 closest-hit 递归发射，而由 raygen 的显式循环再次调用 `optixTrace`。

## 5. 场景链：CUDA 数据、GAS 与 IAS

pipeline 已存在后，主机才上传纹理、材质、灯和几何。几何侧的数据链是：

~~~text
CPU Scene / MeshResource
  → CUDA DeviceBuffer（position、normal、UV、index）
  → OptixBuildInput
  → 每份 mesh 资源或解析 primitive 的 GAS
  → OptixInstance（transform、GAS handle、sbtOffset）
  → IAS
  → LaunchParams.traversable
~~~

[第 6 章第 6 节](06-geometry-visibility-and-bvh.md#6-spectraldock-的-gas-与-ias)给出同步源码片段：`build_mesh` 把 CUDA 设备指针写入三角形 `OptixBuildInput`，`compact_gas` 按收益决定是否压缩；`build_ias` 再上传 `OptixInstance` 数组，并经同一 `compact_gas` 路径构建和按收益压缩 IAS。

同一 mesh 的多个对象共享一份 GAS，避免重复上传和构建；每个实例仍有自己的变换和 SBT 偏移。GAS/IAS 回答“射线可能命中什么”，下一节的 SBT 回答“命中后执行哪个程序并读取哪份对象数据”。

## 6. SBT：绑定对象、射线类型与程序

Shader Binding Table 可理解为 GPU 上的命中分发表。每个对象有两条 hitgroup record，索引为

$$
\text{record index}
=2\times\text{object index}+\text{ray type}.
$$

IAS instance 的 `sbtOffset = object index * 2`；`optixTrace` 再用 ray type 选择 radiance 或 shadow record。每条 record 包含与 primitive 类别匹配的程序 header，以及该对象自己的 `GeometryData`、正反面材质索引、alpha 和灯索引；mesh record 还保存顶点、法线、UV 与索引设备指针。完整材质数组由 `LaunchParams.materials` 提供。

<!-- source-snippet id="optix-sbt-hit-records" path="src/optix_renderer.cpp" anchor="hits.reserve(hitgroups.size() * kRayTypeCount);" -->
```cpp
  std::vector<SbtRecord<HitgroupData>> hits;
  hits.reserve(hitgroups.size() * kRayTypeCount);
  for (const HitgroupData& hitgroup : hitgroups) {
    const DeviceGeometryData& geometry = hitgroup.geometry;
    if (geometry.primitive_type < 0 ||
        static_cast<std::size_t>(geometry.primitive_type) >= programs.hit.size())
      throw std::runtime_error("invalid device primitive type");
    for (unsigned int ray = 0; ray < kRayTypeCount; ++ray) {
      SbtRecord<HitgroupData> record{};
      record.data = hitgroup;
      check_optix(
          optixSbtRecordPackHeader(
              programs.hit[geometry.primitive_type][ray], &record),
          "optixSbtRecordPackHeader(hit)");
      hits.push_back(record);
    }
  }
  storage.hit.allocate(tracker, hits.size() * sizeof(hits.front()));
  storage.hit.upload(hits);
```

外层循环对应对象，内层依次追加 radiance 和 shadow record，正好实现上式。共享同一 mesh GAS 的实例仍由各自的 `OptixInstance.transform` 保留变换，并由各自的 SBT record 保留材质索引、alpha 与灯索引。`make_sbt` 还各自创建一条 raygen record 和两条 miss records，并把这些设备地址写入 `OptixShaderBindingTable`。

## 7. LaunchParams：一次 launch 的全局上下文

SBT 完成后，主机分配并清零 beauty、albedo、normal 和逐像素 ray-count 缓冲区，再填写 `LaunchParams`。其中包括 IAS 根、输出指针、图像尺寸、spp、最大反弹数、随机种子、相机、背景、材质、纹理、灯和 `scene_epsilon`。

<!-- source-snippet id="optix-launch-params-population" path="src/optix_renderer.cpp" anchor="parameters.traversable = ias.handle;" -->
```cpp
  LaunchParams parameters{};
  parameters.traversable = ias.handle;
  parameters.beauty =
      reinterpret_cast<float4*>(beauty.pointer());
  parameters.albedo =
      reinterpret_cast<float4*>(albedo.pointer());
  parameters.normal =
      reinterpret_cast<float3*>(normal.pointer());
  parameters.width = settings.width;
  parameters.height = settings.height;
  parameters.spp = settings.spp;
  parameters.max_depth = settings.max_depth;
  parameters.seed = settings.seed;
  parameters.camera = camera_for(scene, settings);
```

`traversable` 是遍历入口，三个图像指针是 raygen 的输出，尺寸与 spp 决定工作量，`max_depth` 控制路径循环上限，`seed` 和相机决定初始样本。结构体整体上传到设备后，设备程序通过常量 `params` 访问。

曝光不属于路径追踪的输入，因此不进入 `LaunchParams`。OptiX launch 和可选降噪完成后，主机才把 `settings.exposure` 直接传给纯 CUDA postprocess kernel；它只影响 HDR beauty 如何映射到显示输出，不影响射线遍历、着色或降噪输入。

## 8. 调用 optixLaunch：二维像素网格

`optixLaunch` 使用刚上传的参数、SBT 和 `width × height × 1` 的 launch 维度：

<!-- source-snippet id="optix-two-dimensional-launch" path="src/optix_renderer.cpp" anchor="settings.width, settings.height, 1" -->
```cpp
  DeviceBuffer launch_parameters(tracker, sizeof(parameters));
  launch_parameters.upload(&parameters, sizeof(parameters), stream);
  Event render_start, render_end;
  render_start.record(stream);
  {
    NvtxRange range("OptiX path trace and shading");
    check_optix(optixLaunch(
                    optix.pipeline, stream, launch_parameters.pointer(),
                    sizeof(parameters), &sbt.table,
                    settings.width, settings.height, 1),
                "optixLaunch");
```

每个 raygen invocation 负责一个像素，在内部串行循环 spp 条样本路径；不同像素并行执行。末尾的 1 是 launch 的固定深度，不是 spp 或路径深度。路径长度、材质分支和阴影结果不同会造成 warp 分支发散；俄罗斯轮盘减少长路径工作，也让线程循环次数更不一致。

`optixLaunch` 对 CUDA stream 是异步的。代码在 launch 后记录 event 并等待它，只把这段区间计入 `render_ms`；GAS/IAS 构建和可选 denoiser 分别计时。

## 9. 遍历、求交、payload 与自定义着色

raygen 的 radiance 查询把局部 `SurfaceHit` 指针拆成两个 32 位 payload，再对 IAS 根调用 `optixTrace`：

<!-- source-snippet id="optix-radiance-traversal" path="src/device_programs.cu" anchor="optixTrace(params.traversable" -->
```cpp
static __forceinline__ __device__ SurfaceHit trace_radiance(
    float3 origin, float3 direction, unsigned long long& traced_rays,
    float maximum_distance = kInfinity) {
  SurfaceHit hit = {};
  hit.hit = 0;
  hit.distance = kInfinity;
  unsigned int p0;
  unsigned int p1;
  pack_pointer(&hit, p0, p1);
  ++traced_rays;
  optixTrace(params.traversable, origin, direction, params.scene_epsilon,
             maximum_distance, 0.0f, OptixVisibilityMask(255),
             OPTIX_RAY_FLAG_NONE, spectraldock::kRayRadiance,
             spectraldock::kRayTypeCount, spectraldock::kRayRadiance, p0, p1);
  return hit;
}
```

一次查询中各类程序的分工如下：

| 阶段 | 何时执行 | 本项目行为 |
|---|---|---|
| traversal | `optixTrace` 内部 | 从 IAS 进入实例对应的 GAS，用 BVH 排除无关包围盒 |
| intersection | 遇到候选 primitive | disk、cylinder、parabola、water surface 和 solid sphere 运行自定义交点代码；普通 sphere、triangle/mesh 使用内建求交 |
| any-hit | 候选交点被报告后 | 对 radiance 和 shadow 都执行 alpha cutoff；shadow 还忽略目标灯自身 |
| closest-hit | radiance 最近有效命中确定后 | 计算位置、几何/着色法线、UV、材质与灯索引，写入 `SurfaceHit` |
| miss | 没有有效命中 | radiance 保留“未命中”，shadow 把 payload 写成“可见” |
| raygen | 每个像素入口 | 评估背景/发光、BSDF、NEE/MIS、throughput、俄罗斯轮盘和反弹循环 |

因此，closest-hit 的主要职责是填写 `SurfaceHit`；完整的自定义着色主要在 `__raygen__pathtrace` 的迭代循环中完成，并不是在 closest-hit 中递归发射下一条路径射线：

~~~text
raygen
  ├─ optixTrace(radiance) → SurfaceHit 或 miss
  ├─ 评估背景/发光、BSDF 与 NEE/MIS
  ├─ 可能 optixTrace(shadow) → 可见性布尔值
  ├─ 粗糙介电透射 NEE：在栈副本中更新当前边界并计算 Beer 段
  ├─ 更新 radiance、throughput、PDF 与俄罗斯轮盘
  └─ 改写 ray origin/direction，进入下一次 bounce
~~~

### 9.1 Radiance payload

payload 0 和 1 合并为 `SurfaceHit*`。miss 不填写命中数据，closest-hit 通过该指针写入结果；`optixTrace` 返回后，raygen 像读取普通查询结果一样消费它。

### 9.2 Shadow payload 与透明边界语义

shadow payload 0 初始为 0：若一路未命中，miss 写 1；遇到有效遮挡则用 `OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT` 终止并保留 0。payload 1 保存目标灯索引，使 any-hit 忽略终点处那盏灯自己的几何。这个二值 shadow 查询禁用 closest-hit，只需要遍历、intersection/内建求交、any-hit 和 miss。

含水场景也使用同一个二值查询。粗糙介电 NEE 若连接当前界面的透射侧，raygen 在发射 shadow 前把 origin 移到正确一侧，并在 `MediumState` 副本中切换这**一次**边界；shadow 段可见后再按副本顶层介质计算 Beer。连接线上若遇到下一层水或玻璃，any-hit 会像处理不透明表面一样终止查询，因为一条直线不能代表经过第二个折射事件的光路。数学、介质栈与 MNEE 边界见[第 12 章第 6、7 节](12-runtime-analytic-water.md#6-粗糙水面的-nee只连接当前散射事件)。

两类 SBT ray type 使用同一 IAS，但由 ray type、SBT stride 和 miss index 选择不同 records；pipeline 因而只需声明两个 32 位 payload values。含水路径不增加第三种 SBT ray type，也不再为一条直接光连接反复发射 radiance 查询。

## 10. OptiX Denoiser 与纯 CUDA 输出边界

`optixLaunch` 结束时得到线性 HDR beauty，以及首命中 albedo/normal guides：

~~~text
OptiX ray tracing pipeline
  → raw linear HDR beauty + albedo/normal
  ├→ 可选 D2H + CPU 写原始线性 RGB PFM
  └→ 可选 OptiX HDR Denoiser
  → raw 或 denoised final_beauty
  → 纯 CUDA postprocess kernel
  → 设备端 RGBA8
  → D2H + stream synchronize
  → CPU RenderResult
  → libpng 写 PNG
~~~

`denoise=false` 时直接使用 raw beauty；`denoise=true` 时，`run_denoiser` 创建 HDR denoiser，查询内存、分配并 setup state/scratch，计算 HDR intensity，绑定 beauty/albedo/normal，invoke 后同步。完整 API 顺序与源码片段见[第 8 章第 3 节](08-denoising-color-and-output.md#3-optix-hdr-降噪)。

降噪之后的 `spectraldockLaunchPostprocess` 是普通 CUDA kernel，不是 RayGen、Miss 或 Hit 程序。它完成 EV 曝光、ACES 风格曲线、sRGB 编码和 RGBA8 量化。若请求 `--linear-output`，原始 `beauty` 另行 D2H，不经过 Denoiser 或显示变换。随后 stream 同步形成 GPU 完成边界；`render_optix` 返回 `RenderResult`，命令行主机代码分别用 libpng 写 PNG、用 PFM writer 写线性 RGB。

## 11. RAII 销毁与部署边界

`render_optix` 把一帧资源放在局部 RAII 对象中。正常返回或抛出异常时，设备缓冲、GAS/IAS backing buffers、SBT、纹理对象、events 和 stream 按作用域逆序释放；`OptixState` 负责 OptiX 句柄：

<!-- source-snippet id="optix-state-teardown" path="src/optix_renderer.cpp" anchor="~OptixState()" -->
```cpp
struct OptixState {
  OptixDeviceContext context = nullptr;
  OptixModule module = nullptr;
  OptixModule sphere_module = nullptr;
  std::vector<OptixProgramGroup> groups;
  OptixPipeline pipeline = nullptr;
  OptixDenoiser denoiser = nullptr;
  ~OptixState() {
    if (denoiser) optixDenoiserDestroy(denoiser);
    if (pipeline) optixPipelineDestroy(pipeline);
    for (auto it = groups.rbegin(); it != groups.rend(); ++it)
      if (*it) optixProgramGroupDestroy(*it);
    if (sphere_module) optixModuleDestroy(sphere_module);
    if (module) optixModuleDestroy(module);
    if (context) optixDeviceContextDestroy(context);
  }
};
```

销毁顺序是 denoiser → pipeline → 逆序 program groups → 内建 sphere module → 主 module → OptiX context。CUDA primary context 由 `cudaSetDevice`/runtime 建立并由本函数借用，代码没有在此调用 `cuCtxDestroy` 或 `cudaDeviceReset`。

这也解释了当前的性能与部署边界：每次 `render_optix` 都重新建立并销毁 OptiX device context、pipeline、GAS/IAS、SBT、纹理与设备缓冲，没有跨帧缓存；同时运行时从构建树中的绝对路径读取 `.optixir`。v0.1 因而面向构建树或容器内的命令行离线渲染，不提供可重定位 install 布局。

[上一章：几何、可见性与 BVH](06-geometry-visibility-and-bvh.md) · [返回目录](README.md) · [下一章：降噪、色调映射与输出](08-denoising-color-and-output.md)
