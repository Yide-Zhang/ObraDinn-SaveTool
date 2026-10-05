"""难度补丁相关的开发工具与共享模块。

这个 `__init__.py` 让 `hardcore/` 成为一个可导入的包，这样玩家侧的
`patcher/` 可以直接复用 `hardcore.lang_bundle`（UnityFS 读取器）等，
而不必复制一份。

注意：里面的 `gen/`（C# + Cecil）与 `_*` 目录是**开发期**用的，不随玩家侧分发。
"""
