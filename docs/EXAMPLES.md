# 五个能力展示场景

正式图由 `./scripts/render-examples.sh --preset final` 直接写入 `docs/gallery/`；下列链接保持原始 1920×1080 PNG，不使用缩略图替代。

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

## 运行

```bash
# 全部预览
./scripts/render-examples.sh --preset preview

# 全部正式图
./scripts/render-examples.sh --preset final

# 只渲染指定场景
./scripts/render-examples.sh --preset preview neon-koi reflector-laboratory
```

正式静态几何统计和 RTX 5090 数据见 [BENCHMARK.md](BENCHMARK.md)。图像/模型来源与 CC0 使用条件见 [ASSETS.md](ASSETS.md)。
