import importlib, sys

# 清除所有已缓存的 settings
for mod in list(sys.modules.keys()):
    if 'config' in mod:
        importlib.reload(sys.modules[mod])

from app.config import settings
print(settings.rerank_model)  # 现在应该能访问了