# 示例画廊：五个内置场景与一个按需 PhysX 场景

五个内置场景的正式图由 `./scripts/render-examples.sh --preset final` 直接写入 `docs/gallery/`；下列链接保持原始 1920×1080 PNG，不使用缩略图替代。Kinetic Foundry 由独立的 PhysX 流程生成，不加入默认批处理。

## Material Cathedral

![Material Cathedral](gallery/material-cathedral.png)

三个胶囊吉祥物实例共享一份 5,816-triangle GAS，分别使用陶瓷、粗糙金属和玻璃。封闭建筑、矩形主光与圆盘补光用于观察 GGX、Fresnel、MIS、色彩反弹和 `T * Rz * Ry * Rx * S` 实例变换。

## Neon Koi

![Neon Koi](gallery/neon-koi.png)

透明锦鲤剪影、纹理 emitter、青/洋红面积光、无文字电路墙和湿润金属地面围绕一个深色金属胶囊吉祥物，集中展示 alpha any-hit、图像纹理、共享网格、彩色间接光、景深和 AI 降噪。

## Celestial Archive

![Celestial Archive](gallery/celestial-archive.png)

青铜胶囊吉祥物作为中央展品，配两颗为本项目生成的 2:1 纹理星球、玻璃天体、天空渐变与太阳瓣，展示网格实例、球面 UV、天空照明和反射折射。

## Reflector Laboratory

![Reflector Laboratory](gallery/reflector-laboratory.png)

白色陶瓷胶囊吉祥物置于两面抛物面反射器之间，组合 cylinder、disk、单面材质及 rectangle/disk/sphere 三种面积光，验证自定义交点与正反面语义。

## Benchmark Harbor

![Benchmark Harbor](gallery/benchmark-harbor.png)

“泡泡海上的吉祥物船队”由 16 个四色胶囊吉祥物实例共享一份 5,816-triangle GAS，并由固定 seed `20260707` 生成 1,024 个互不重叠的球形波浪。该场景覆盖大 IAS、确定性生成、BVH 构建和吞吐率。

## Kinetic Foundry (PhysX)

![Kinetic Foundry](gallery/kinetic-foundry.png)

该按需场景使用 PhysX 5.8.0 GPU 刚体模拟 24 个采用 capsule 碰撞代理的吉祥物与 192 颗钢珠，并在固定第 300 步（2.5 秒）截取撞击峰值；sidecar 记录 `sleeping_dynamic_actors=0`，即没有动态 actor 进入 sleeping 状态。SpectralDock/OptiX 渲染的是这一时刻清晰的静态单帧，不含 motion blur，不应解读为系统的最终静止状态。仓库只保留正式 PNG、渲染 stats 和同 stem 的 `.physics.json` 生成记录，不提交中间 `scenes/generated/kinetic-foundry.json`。PhysX 不参与路径追踪，也不会成为运行五个内置场景时的依赖；复现边界和命令见 [PhysX 场景说明](PHYSX_SCENE.md)。

## 运行

```bash
# 全部预览
./scripts/render-examples.sh --preset preview

# 全部正式图
./scripts/render-examples.sh --preset final

# 只渲染指定场景
./scripts/render-examples.sh --preset preview neon-koi reflector-laboratory
```

上述命令只处理五个内置场景。按需生成并渲染 Kinetic Foundry：

```bash
./scripts/build-physx-image.sh
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh --preset preview

# 仅维护者在验收后替换受版本控制的同名三件套；不增加资产数量
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh --preset final
```

正式静态几何统计和 RTX 5090 数据见 [BENCHMARK.md](BENCHMARK.md)。图像/模型来源与 CC0 使用条件见 [ASSETS.md](ASSETS.md)。
