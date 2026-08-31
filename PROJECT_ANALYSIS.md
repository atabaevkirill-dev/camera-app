# 📹 ONVIF Reticle Station — Анализ проекта

## 📌 Обзор проекта

**Название:** ONVIF Reticle Station  
**Язык:** Python 3.10+  
**Тип:** Десктопное приложение для мониторинга и записи IP-камер  
**Фреймворк UI:** PySide6 (Qt 6)  
**Лицензия:** Не указана  
**Репозиторий:** `atabaevkirill-dev/camera-app`

### Основное назначение
Ультрасовременная станция наблюдения для двух IP-камер (промышленная камера + тепловизор) в стиле SENTINEL NVR с функциями:
- Живой мониторинг двух камер (ONVIF/RTSP или USB-webcam)
- Сплит-запись обеих камер в один видеофайл
- Наложение прицельных сеток (Cross, Duplex, Mil-Dot)
- PTZ-управление (D-pad, пресеты, домой, автофокус)
- Архив с превью, поиском и фильтрацией
- Встроенный видеоплеер и видеоредактор
- Журнал событий
- Автопоиск камер через WS-Discovery
- Двуязычный интерфейс (RU/EN)

---

## 🏗️ Архитектура и структура

### Многоуровневая архитектура

```
┌─────────────────────────────────────────────────┐
│              UI Layer (PySide6/Qt)              │
│  (MainWindow, VideoPanel, Dialogs, Widgets)    │
├─────────────────────────────────────────────────┤
│         Business Logic Layer (Workers)          │
│  (StreamWorker, SplitRecorder, ArchiveDB,      │
│   EditorWidget, EventBus, PTZPad)              │
├─────────────────────────────────────────────────┤
│            Utilities & Services Layer           │
│  (OnvifClient, Discovery, MediaConvert,        │
│   Profiles, I18n, Theme, Logging)              │
├─────────────────────────────────────────────────┤
│          External Libraries & APIs              │
│  (OpenCV, FFmpeg, ONVIF SOAP, SQLite)          │
└─────────────────────────────────────────────────┘
```

### Модульная структура (`app/`)

#### **Ядро приложения**
- **`main.py`** — точка входа, инициализация приложения, селф-тест (`--selftest`)
- **`main_window.py`** — главное окно: вкладки (Monitor/Archive/Editor/Journal), меню, управление камерами
- **`theme.py`** — дизайн-система в стиле SENTINEL NVR (палитра цветов, глобальные стили QSS)

#### **Обработка потоков видео**
- **`stream_worker.py`** — захват RTSP-потоков через OpenCV в отдельном потоке, реконнект, запись в видеофайл
- **`split_recorder.py`** — сплит-запись двух камер (бок о бок) в один видеофайл + отрисовка прицела
- **`video_panel.py`** — виджет отображения видеопотока на экране

#### **Система прицелов**
- **`reticle.py`** — класс `ReticleStyle` для описания прицела (тип, цвет, толщина, длина)
- **`reticle_editor.py`** — редактор параметров прицела (цвет, стиль, перетаскивание)

#### **ONVIF и управление камерами**
- **`onvif_client.py`** — лёгкий ONVIF-клиент (парсинг SOAP вручную, без зависимости `zeep`) для:
  - Получения возможностей камеры
  - Извлечения профилей медиа
  - Получения RTSP URI потока
  - Управления видеоисточником
- **`discovery.py`** / **`discover_dialog.py`** — автопоиск камер через WS-Discovery (UDP 3702)
- **`ptz_pad.py`** — виджет D-pad для PTZ-управления (pan, tilt, zoom, focus)

#### **Управление профилями камер**
- **`profiles.py`** — загрузка/сохранение конфигурации камер из `camera_profiles.json`
- **`settings_dialog.py`** — диалог настроек камер (хост, порт, логин, пароль, RTSP URL)

#### **Архив и медиа**
- **`archive_db.py`** — SQLite-база архива с функциями:
  - Сохранение записей видео
  - Генерация миниатюр (0.3:1)
  - Автоконвертация в H.264 MP4
  - Управление версиями схемы БД
- **`archive_dialog.py`** — галерея архива с:
  - Поиском по датам, камерам, типам
  - Встроенным видеоплеером (скорость ×0.5–×4, покадровый шаг)
  - Удалением с подтверждением
- **`editor_dialog.py`** — видеоредактор с функциями:
  - Обрезка таймлайна
  - Скорость ×0.25–×4
  - Разрешение: 1080p / 720p / 480p
  - Качество: Low / Medium / High / Max (CRF 30–20)
  - Форматы: MP4 / AVI / MKV
  - Ч/Б и контраст-фильтры
  - Прогресс-бар экспорта

#### **Медиа-обработка**
- **`media_convert.py`** — ffmpeg-конвейер для транскодирования и зондирования кодеков
  - Использует встроенный `imageio-ffmpeg` или системный FFmpeg
  - Проверка доступности кодека H.264

#### **UI/UX**
- **`i18n.py`** — интернационализация (RU/EN)
- **`icons.py`** — утилиты для работы со значками
- **`logutil.py`** — логирование (файл: `logs/app.log`)
- **`journal.py`** — журнал событий (EventBus + JournalView) с уровнями логирования
- **`app_settings_dialog.py`** — диалог глобальных настроек приложения

#### **Инструменты**
- **`tools/selfcheck.py`** — headless-тест UI (smoke-тест без дисплея)

---

## 🔧 Технологический стек

### Зависимости (requirements.txt)
```
PySide6 >= 6.5          # Qt 6 бинdings для Python
opencv-python >= 4.8   # Захват видео (RTSP, webcam), обработка кадров
requests >= 2.31       # HTTP-клиент для ONVIF SOAP
Pillow >= 10.0.0       # Обработка изображений (миниатюры)
imageio-ffmpeg         # Встроенный FFmpeg для транскодирования
```

### Ключевые технологии
| Компонент | Технология | Назначение |
|-----------|-----------|-----------|
| UI | PySide6 (Qt 6) | Десктопное приложение, кроссплатформа |
| Видеозахват | OpenCV (cv2) | RTSP-потоки, webcam, обработка кадров |
| Интеграция камер | ONVIF (SOAP) | Управление IP-камерами |
| Обнаружение камер | WS-Discovery (UDP) | Auto-discovery по сети |
| Запись видео | cv2.VideoWriter + FFmpeg | MP4, AVI, MKV |
| Архив | SQLite3 | Метаданные видео, миниатюры |
| Обработка изображений | Pillow (PIL) | Генерация превью |
| Транскодирование | FFmpeg | H.264 MP4 конверсия |

---

## 📊 Поток данных и жизненный цикл

### Инициализация приложения
1. `main.py` запускается, устанавливает логирование
2. Загружается конфигурация камер (`camera_profiles.json`)
3. Применяется тема (SENTINEL NVR стиль)
4. Создается главное окно (`MainWindow`)
5. Два потока `StreamWorker` инициализируются для каждой камеры

### Захват видео
```
StreamWorker (QThread)
  ↓
OpenCV VideoCapture (RTSP/webcam)
  ↓
Frame grabbing loop (configurable FPS: 25 default)
  ↓
├─ Video display (VideoPanel via latest frame)
├─ Recording (if enabled → SplitRecorder или отдельный VideoWriter)
└─ Status/error signals → MainWindow
```

### Сплит-запись
```
Frame1 (cam1) + Frame2 (cam2)
  ↓
SplitRecorder (resize to 16:9)
  ↓
├─ Draw reticle if enabled (cv2 на кадре)
├─ Concatenate frames (side-by-side)
├─ Encode to H.264 MP4
└─ Save as split_TIMESTAMP.mp4
```

### Архивирование
```
Video file created
  ↓
ArchiveDB (detect by file extension)
  ↓
├─ Extract thumbnail (OpenCV at 1/3)
├─ Transcode to H.264 MP4 (if needed)
├─ Insert metadata into SQLite
└─ Store in archive/
```

### Редактирование
```
EditorWidget (user selects trim, speed, resolution, format)
  ↓
FFmpeg command builder
  ↓
ExportWorker (QThread)
  ↓
Execute ffmpeg with progress parsing
  ↓
Save output file → Archive
```

---

## 🔌 Ключевые компоненты и их взаимодействие

### 1. **StreamWorker** (stream_worker.py)
```python
class StreamWorker(QThread):
    statusChanged = Signal(str)   # "connecting", "online", "offline", "error"
    message = Signal(str)         # диагностика
    streamLost = Signal(int)      # индекс камеры
    
    def run(self):
        # Бесконечный цикл захвата
        while not self._stop_flag:
            ret, frame = cap.read()
            # Запись, если включена
            if self._recording:
                self._write_frame(frame)
            # Сигнал для отображения
            self.latest_frame = frame
```

**Особенности:**
- Переподключение при разрыве соединения (3 попытки)
- Низкая задержка (UDP vs TCP в зависимости от опций)
- Потокобезопасное получение кадра через `get_frame()`
- Отдельный поток для записи (избегает блокировки UI)

### 2. **SplitRecorder** (split_recorder.py)
```python
class SplitRecorder(QThread):
    """Записывает две камеры бок о бок в один видеофайл"""
    def run(self):
        while recording:
            frame1 = worker1.get_frame()
            frame2 = worker2.get_frame()
            # Ресайз обоих до 16:9
            # Рисование прицела (если включено)
            if reticle_enabled:
                draw_reticle_on_frame(frame1, style_dict, dx, dy)
                draw_reticle_on_frame(frame2, style_dict, dx, dy)
            # Конкатенация side-by-side
            split_frame = hstack([frame1, frame2])
            # Запись в MP4
            writer.write(split_frame)
```

**Особенности:**
- Синхронизация двух потоков видео в один файл
- Отрисовка прицела прямо на кадре (cv2)
- Прицел можно перетаскивать в реальном времени (dx, dy)

### 3. **ArchiveDB** (archive_db.py)
```python
class ArchiveDB:
    """SQLite-архив с метаданными видео"""
    schema: archive_items(
        id INT PRIMARY KEY,
        filename TEXT,
        cam_index INT,  # 0=split, 1=cam1, 2=cam2
        rec_type TEXT,  # 'split', 'individual'
        timestamp INT,  # unix time
        duration REAL,  # секунды
        codec TEXT,     # 'h264'
        thumbnail_path TEXT,
        created_at DATETIME
    )
```

**Функции:**
- Автоматическая генерация миниатюр
- Транскодирование в H.264 при необходимости
- Версионирование схемы БД
- Поддержка форматов: MP4, AVI, MOV, MKV, PNG

### 4. **OnvifClient** (onvif_client.py)
```python
class OnvifClient:
    """Лёгкий ONVIF-клиент без zeep"""
    def __init__(self, host, port, username, password, auth):
        self.host = host
        self.port = port
        # SOAP-запросы через requests
    
    def get_capabilities(self): ...
    def get_profiles(self): ...
    def get_stream_uri(profile_token): ...
    def get_video_source_configurations(self): ...
    def ptz_continue_move(velocity): ...  # PTZ
```

**Особенности:**
- Без тяжелой зависимости `zeep`
- Ручной парсинг XML SOAP
- Инъекция credentials в RTSP URL
- Поддержка Digest auth

### 5. **MainWindow** (main_window.py)
```python
class MainWindow(QMainWindow):
    # Две вкладки видео (cam1, cam2)
    # Сплит-записьи кнопка
    # Меню: Service (auto-discovery, settings), View (monitor/archive/editor/journal)
    # PTZ Pad (если камера поддерживает)
    # Status bar (статус, события)
    
    def _start_recording_split(self):
        """Запуск сплит-записи обеих камер"""
        self.split_recorder.start()
    
    def _on_archive_syncer(self):
        """Периодическая синхронизация новых видео в архив"""
        ...
```

### 6. **ReticleEditor** (reticle_editor.py)
```python
class ReticleEditor(QWidget):
    """Интерактивный редактор прицела"""
    # Выбор стиля: Cross, Duplex, Mil-Dot
    # Цвет (RGB picker)
    # Толщина линии
    # Длина линии
    # Перетаскивание мышью (dx, dy offset)
    # Preview в реальном времени
```

### 7. **DiscoveryWorker** (discovery.py)
```python
class DiscoveryWorker(QThread):
    """WS-Discovery: отправка M-SEARCH UDP 239.255.255.250:3702"""
    # Сканирование сети на наличие ONVIF-устройств
    # Парсинг ответов (WSA-Addressing)
    # Извлечение адресов и моделей камер
```

---

## 💾 Хранение данных

### Конфигурация
- **`camera_profiles.json`** (не в git) — профили камер:
  ```json
  {
    "language": "ru",
    "cam1": {
      "conn": {"host": "192.168.1.100", "port": 80, "username": "admin", "password": "***"},
      "rtsp": {"url": "rtsp://192.168.1.100/stream"}
    },
    "cam2": {...}
  }
  ```

### Архив
- **`archive/`** — видеофайлы и экспорты
- **`archive.db`** — SQLite метаданные
- **`thumbnails/`** — генерированные превью (v3)
- **`logs/app.log`** — лог приложения

---

## 🚀 Процесс запуска

### Windows
```bat
run.bat
  ↓
создаёт venv (если не существует)
  ↓
установка requirements.txt
  ↓
python main.py
```

### Linux/macOS
```bash
./run.sh
  ↓
создаёт venv (если не существует)
  ↓
установка requirements.txt
  ↓
python3 main.py
```

### Selftest (smoke-тест)
```bash
python main.py --selftest
  ↓
QT_QPA_PLATFORM=offscreen (no display needed)
  ↓
Инициализация UI
  ↓
Закрытие через 1.5 сек
  ↓
Exit code 0 = OK
```

---

## 📋 Требования к окружению

### ОС
- Windows, Linux, macOS (кроссплатформа)

### Python
- 3.10+ (проверено на 3.14)

### Системные зависимости
- **Linux:** `python3-venv`, `libgl1` (для OpenCV)
- **macOS:** разрешение на доступ к камере/сети
- **FFmpeg:** опционально (встроенный `imageio-ffmpeg` используется по умолчанию)

### Сетевые требования
- UDP 3702 для WS-Discovery (auto-discovery)
- RTSP/HTTP для потоков с камер
- Настройки firewall для локальной сети

---

## 🔒 Безопасность и Privacy

### Приватность данных
- ✅ Пароли камер хранятся локально в `camera_profiles.json` (не в git)
- ✅ Архив, записи и скриншоты — локальные данные
- ✅ Ничего не отправляется в сеть, кроме трафика к камерам
- ⚠️ Credentials хранятся в открытом виде (рекомендуется ограничить доступ к файлу)

### Аутентификация
- Поддержка Digest auth для ONVIF
- Инъекция credentials в RTSP URL (username:password@host)

---

## 🎨 Пользовательский интерфейс

### Дизайн-система
- **Стиль:** SENTINEL NVR (темная тема для наблюдения)
- **Палитра:** 
  - Основной цвет: голубой (accent)
  - Фон: темный
  - Текст: светлый
  - Ошибки/Предупреждения: красный

### Компоненты UI
- **Вкладки:** Monitor (живой просмотр) → Archive → Editor → Journal
- **Меню:** Service, View, Help
- **Статус-бар:** статус подключения, события
- **Диалоги:** Settings (камеры), Discovery (поиск), Archive (галерея)

---

## 🧪 Тестирование

### Selftest
```bash
python main.py --selftest
```
- Headless-проверка инициализации UI
- Проверка загрузки конфигурации
- Проверка подключения (если камеры доступны)
- Время выполнения: ~1.5 сек

### Ручное тестирование
- Подключение камер (ONVIF/RTSP/webcam)
- Live monitoring
- Запись обеих камер
- Архивирование и экспорт
- Язык интерфейса (RU/EN)

---

## 📈 Масштабируемость и производительность

### Оптимизация
- **Multi-threading:** StreamWorker, SplitRecorder, ArchiveDB, ExportWorker — все в отдельных потоках
- **Синхронизация:** threading.Lock для захвата кадров
- **Низкая задержка:** UDP RTSP, H.264 кодирование
- **Кэширование миниатюр:** версионирование (v3)

### Ограничения
- **Две камеры max** (дизайн-система фокусируется на 2 потоках)
- **Разрешение:** 1080p+ (зависит от камер и ПК)
- **FPS:** 25 fps default (конфигурируемый)
- **Качество видео:** зависит от настроек FFmpeg

---

## 🔮 Расширяемость

### Области для расширения
1. **Поддержка больше камер** — рефакторинг UI (grid вместо splitter)
2. **Облачный архив** — интеграция S3/Google Cloud
3. **Аналитика видео** — интеграция ML (detection, tracking)
4. **WebUI** — добавление web-интерфейса
5. **Плагины** — система расширений для фильтров, кодеков
6. **API** — REST API для интеграции

---

## 📝 Итоги

**ONVIF Reticle Station** — это *специализированное десктопное приложение* для профессионального мониторинга двух IP-камер с фокусом на:
- ✅ Надежный ONVIF/RTSP захват с автовосстановлением
- ✅ Синхронная сплит-запись в один файл
- ✅ Интерактивные прицельные сетки
- ✅ Встроенное архивирование с поиском и редактором
- ✅ Чистый UI в стиле профессионального видеонаблюдения

**Архитектура** опирается на многопоточность, слабую связанность модулей и кроссплатформенность (PySide6 + OpenCV).

**Технологический стек** минималистичен и зависит только от 5 пакетов Python, что обеспечивает:
- Простоту развертывания
- Быструю инициализацию
- Стабильность на слабых ПК
