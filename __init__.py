bl_info = {
    "name": "Octavia Anima-DAW",
    "author": "Synesthesia Team",
    "version": (0, 2, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Octavia",
    "description": "Модульный интерфейс Octavia DAW для Blender 5.1+",
    "category": "Animation",
}

import sys
import importlib

# 🔥 СВЕРХЗВУКОВОЙ ДВИЖОК ГЛУБОКОЙ ПЕРЕЗАГРУЗКИ ПОДМОДУЛЕЙ (DEEP RELOAD)
# Выгребаем из памяти Питона абсолютно все файлы нашего аддона
prefix = __package__ + "."
submodules_to_reload = sorted(
    [name for name in sys.modules if name.startswith(prefix)],
    key=lambda name: name.count('.'),
    reverse=True
)

# Перезагружаем их строго снизу вверх (от глубоких файлов к корню папок)
for name in submodules_to_reload:
    try:
        importlib.reload(sys.modules[name])
    except Exception as e:
        print(f"[Octavia Reload Warning] Не удалось обновить {name}: {e}")

# Теперь спокойно импортируем обновленные модули
from . import workspace
from . import operators
from . import interface
from . import nodes
from . import runtime_properties

def register():
    # Сначала классы, затем зависящие от них свойства и остальные системы
    operators.register()
    runtime_properties.register()
    workspace.register()
    interface.register()

def unregister():
    # Отключаем в порядке, обратном регистрации
    interface.unregister()
    workspace.unregister()
    runtime_properties.unregister()
    operators.unregister()

if __name__ == "__main__":
    register()