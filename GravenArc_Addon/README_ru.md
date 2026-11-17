# GravenArc Toolkit 1.2.0 — установка в Blender 5.2 LTS

![Кисти](../GravenArc_Library/brushes/brushes_preview.png)
![Ювелирные инструменты](../GravenArc_Library/jewelry_tools/demo/demo_render.png)


Один файл **gravenarc_toolkit-1.2.0.zip** (≈19 МБ) содержит всё:
- 25 кистей «GA …» в стиле ZBrush;
- 3 alpha-кисти с орнаментами;
- 103 шаблона (кольца, шинки, кулоны, касты, камни, геометрия, основы для лепки);
- **ювелирные инструменты** в духе Rhino/RhinoGold: камни 13 огранок, касты, вырезы, паве, камни по кривой, шинка по размеру, ресайз, гравировка, вес металла, проверка для литья, усадка, отчёт;
- 61 ювелирный ассет (камни, вырезы, крапановые и глухие касты);
- **скульпт-инструменты** (с 1.2.0): повтор мазка Shift+R, маска последнего мазка Alt+R, метка, отделить/удалить замаскированное, размер/жёсткость кисти Alt+ПКМ, прямая линия Alt+L, папки пресетов кистей, сглаживание. Пошагово: [sculpt_tools/README_ru.md](../GravenArc_Library/sculpt_tools/README_ru.md).

Распаковывать **не нужно**. Если раньше ставили отдельный `gravenarc_jewelry`, выключите и удалите его: всё уже внутри.

## Установка (любой из двух способов)

**Способ 1 — перетаскиванием**
1. Откройте Blender 5.2.
2. Перетащите `gravenarc_toolkit-1.2.0.zip` из папки прямо в окно Blender (на 3D-вьюпорт).
3. В появившемся окне нажмите **OK / Install**. Готово — расширение уже включено.

**Способ 2 — через настройки**
1. **Edit → Preferences** (или `Ctrl+,`).
2. Слева **Get Extensions**.
3. Справа вверху стрелка **⌄** → **Install from Disk…**
4. Выберите `gravenarc_toolkit-1.2.0.zip` → **Install from Disk**.
5. Убедитесь, что в списке **Add-ons** у «GravenArc Toolkit» стоит галочка.

> Если Preferences не сохраняются автоматически: меню ☰ слева внизу → **Save Preferences**.

## Что происходит при включении

- В **Edit → Preferences → File Paths → Asset Libraries** появляется библиотека **GravenArc** (папка внутри расширения). Ничего прописывать вручную не надо.
- В 3D-вьюпорте во вкладке **N › GravenArc** появляются панели **GravenArc Toolkit** (библиотека) и **Ювелирка** (инструменты), а в Sculpt Mode — ещё **Sculpt: Repeat & Mask**, **Sculpt: Photoshop Brush**, **Sculpt: Brush Presets**.
- Включается пай-меню ювелирных инструментов **Shift+Alt+J** (Object Mode).
- При выключении или удалении расширения библиотека убирается сама.

## Где что найти

| Что | Где |
|---|---|
| Панели | 3D Viewport → `N` → вкладка **GravenArc** |
| Кисти и альфы | Sculpt Mode (`Ctrl+Tab`) → полка ассетов внизу вьюпорта; быстрый поиск `Shift+Space` |
| Шаблоны и ювелирные ассеты | Asset Browser (`Shift+F1` или кнопка «Открыть Asset Browser») → библиотека **GravenArc** → перетащить во вьюпорт |
| Ювелирные инструменты | панель **Ювелирка**, пай-меню **Shift+Alt+J**, меню **Shift+A** (Камень, Шинка по размеру) |

## Кнопки панели GravenArc Toolkit

- **Подключить библиотеку заново** — если запись в File Paths случайно удалили.
- **Открыть Asset Browser** — откроет библиотеку GravenArc (если Asset Browser нет на экране — в отдельном окне).
- **Сцена в миллиметрах** — Metric, Unit Scale 0.001, Millimeters: 1 единица = 1 мм. Нажимайте в каждом новом файле перед работой.
- **Подсказки** — инструкции по кистям, альфам, шаблонам и ювелирке; кнопка **EN** рядом открывает английскую версию.

## Настройки расширения

Preferences → Add-ons → GravenArc Toolkit → стрелка: **Импорт ассетов** — *Append* (копия в ваш файл, по умолчанию), *Link* (ссылка) или *Pack*.

## Обновление

Установите новый .zip тем же способом — старая версия заменится, библиотека переподключится.

## Для разработчика

- Исходник расширения: `src/gravenarc_toolkit/` (`__init__.py`, `blender_manifest.toml`, `LICENSE` GPL-3.0-or-later).
- Код ювелирных инструментов: `../GravenArc_Library/jewelry_tools/gravenarc_jewelry/`; при сборке он кладётся в `modules/jewelry/`, ассеты — в `library/jewelry/`.
- Скульпт-модуль: `src/gravenarc_toolkit/modules/sculpt/`; автотест: `BLENDER_USER_RESOURCES=$(mktemp -d) python tests/test_sculpt.py dist/gravenarc_toolkit-1.2.0.zip` (нужен `pip install bpy==5.2.4`).
- Сборка: `bash build_addon.sh` (нужен `blender` 5.2+ в PATH или `BLENDER=/путь/к/blender`). Скрипт берёт ассеты из `../GravenArc_Library/`, делает `blender --command extension validate` и `build`, кладёт .zip в `dist/`.
- Превью и витрины (студийный рендер Cycles, папка `GravenArc_Library/tools/`):
  - `make_brushes.py` → кисти + объёмные иконки (`brush_icons.py`, шар из красного воска с мазком);
  - `alpha_icons.py` → превью альф как серебряный оттиск рельефа;
  - `render_previews.py -- templates jewelry` → превью шаблонов и ювелирных ассетов (золото 750, серебро, бриллиант, воск) и листы `preview_sheet.png`, `jewelry_preview.png`;
  - `render_demo.py` → `jewelry_tools/demo/demo_render.png`;
  - `showcase_sheet.py` → фирменная витрина с подписями (обычный Python 3 + Pillow).
  Запуск: `blender -b --factory-startup --python <скрипт>.py`.
