# 验证与运行统计

SpectralDock 不把某个 GPU 产品、CPU 微架构或逐字节图片摘要定义为支持门槛。
仓库中的 `docs/gallery/*.stats.json` 是对应画面产出时的一次运行记录：它们保留
设备名、驱动、CUDA/OptiX 版本、seed、工作量和计时，便于追溯，但不是跨机器
性能承诺或像素 golden。

完整验收只依赖能力契约：

- 所选 NVIDIA GPU 能成功初始化并执行 OptiX module、pipeline 与 launch；
- 不要求 RT Core，也不按 compute capability 或产品名设置白名单；
- 涉及物理时，PhysX 必须建立有效 CUDA context，并同时使用 GPU dynamics 与
  GPU broadphase；CPU PhysX fallback 禁止；
- 输出必须是 10 bit Rec.2020/PQ HDR AVIF、CICP `9/16/9`、YUV 4:4:4 full
  range 和量化后 AV1 lossless；
- 普通纹理和材质数据图必须是受支持的 8 bit AVIF profile；Radiance RGBE
  `.hdr` 只作为环境贴图输入。

## 计时字段怎样解释

`RenderStats` 把一帧拆成以下主要字段：

| 字段 | 含义 |
| --- | --- |
| `timings_ms.bvh_build` | GAS/IAS 构建及按收益执行的 compaction |
| `timings_ms.render` | 一次 `optixLaunch` 的 CUDA event 时间 |
| `timings_ms.denoise` | 可选 OptiX HDR Denoiser 阶段 |
| `timings_ms.avif_encode` | 主机 HDR 映射与 AVIF 编码/写盘墙钟时间 |
| `timings_ms.total` | native 渲染事务及 HDR AVIF 编码的主机墙钟时间 |
| `traced_rays` | radiance 与二值 shadow 的 `optixTrace` 调用总数 |
| `rays_per_second` | `traced_rays / render`，分母为零时返回 0 |
| `peak_tracked_device_bytes` | 项目 RAII device allocation 记账峰值 |
| `peak_device_bytes` | `cudaMemGetInfo` 相对事务 baseline 的观测峰值 |

`render` 还可能包含解析水面求根、介质栈、Beer 吸收和路径中的体积计算；
volume density evaluation 本身不一定增加 `traced_rays`。不同场景的几何、spp、
depth、体积和自定义求交工作量不同，因此不能只按 rays/s 横向排名。

`total` 从 native 参数检查后开始，并在 `render_optix` 返回的原始时间上加上
紧随其后的 HDR 映射、AVIF 编码与原子写盘时间。它包括
CUDA/OptiX 初始化、纹理解码与上传、pipeline、BVH、SBT、路径追踪、可选降噪、
float beauty 回传、设备信息查询以及 HDR AVIF 写盘；不包括调用前的 Python
SceneBuilder/OBJ 工作，也不包括 stats JSON 编码。它不等于各分项的简单和。

## HDR AVIF 验收

每个 smoke 与对照输出都会解码并检查：

- 单帧、10 bit、YUV 4:4:4、full range；
- BT.2020 primaries、SMPTE ST 2084 transfer、BT.2020 NCL matrix，即 CICP
  `9/16/9`；
- 尺寸正确、像素非空、无 premultiplied alpha；
- 内容亮度元数据存在且不超过固定 1000 nit peak；
- 同一构建和 seed 的确定性 fixture 满足相应数值契约。

AV1 lossless 描述 float beauty 经曝光、Rec.2020 转换、保色相 shoulder、PQ 与
10 bit 量化后的码值压缩；它不意味着 float 到 10 bit 没有量化。需要线性均值、
MSE 或能量比较的 GPU fixture 使用显式进程内测试捕获，设置
`clamp_direct=0, clamp_indirect=0, denoise=False`。捕获不写持久文件，也不进入
stats sidecar。

## PhysX GPU-only 证明

`acceptance.sh` 在任何物理预览之前运行独立 GPU-only probe。private IPC v2
结果的 `schema_version=2`、`generator=spectraldock.physics/2`，并要求后端记录：

- `gpu_dynamics=true`、`gpu_broadphase=true`；
- 有效 CUDA context、TGS、PCM、stabilization 与 `cpu_fallback=false`；
- `cpu_dispatcher_role=host-task-scheduling-only`；
- `gpu_heap_bytes` 包含 samples、total、broad phase、narrow phase、solver 和
  simulation 的 GPU memory statistics。

CPU dispatcher 只调度 PhysX 的宿主任务，不替代 GPU rigid-body dynamics。
worker 创建、模拟或回传任一 GPU 契约失败时立即报错；完整 acceptance 不提供
跳过 PhysX 的入口。

## 定向 GPU fixture

验收覆盖：

- UV、平滑法线、alpha、共享 mesh GAS、逐 primitive 多材质与 custom
  primitive；
- rectangle/disk/sphere/flame 有限灯、point/directional delta 灯、NEE/MIS
  与 firefly 贡献钳位；
- Radiance HDR 环境加载、旋转、uniform/importance 均值与低样本误差；
- flame Delta Tracking、volume NEE、吸收和安全计数器；
- 解析水面求交、粗糙/光滑介电、Fresnel/Snell、Beer、介质栈和三技术
  balance；
- 八个静态教学程序、纯 Renderer Gallery、两个 PhysX Gallery 和两个 PhysX
  教学程序的低成本预览。

这些测试使用结构断言、统计性质、数值容差和视觉检查，不根据 GPU 名称选择
分支。跨 GPU、驱动或编译器的少量浮点差异不会被错误解释成型号不受支持；
真实的数学、profile、GPU-only 或安全计数回归仍会失败。

## 复现

```bash
./scripts/configure.sh Release
./scripts/build.sh Release
source ./scripts/activate.sh Release

# Host-only CTest 与 pytest
./scripts/test.sh

# OptiX + 强制 GPU-only PhysX 的完整验收
./scripts/acceptance.sh
```

OptiX device program 在配置时根据 `nvcc --list-gpu-arch` 选择当前 toolkit 报告
的最老虚拟架构，并生成 portable PTX；不生成设备型号专属 SASS。AOM AVIF
backend 同样保留运行时 CPU dispatch。由此，同一源码不依赖某个 CPU/GPU
型号，同时仍要求实际机器满足本页开头的 GPU 能力契约。
