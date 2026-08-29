# -*- coding: utf-8 -*-
"""Module for managing the archive database."""

import json
import os
import sqlite3
from pathlib import Path

from .logutil import get_logger
from .media_convert import transcode_to_h264, ffmpeg_available, probe_codec

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False
    get_logger("archive_db").warning("OpenCV not found, thumbnails for videos will not be generated.")

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False
    get_logger("archive_db").warning("Pillow not found, thumbnails will not be generated.")


log = get_logger("archive_db")

VIDEO_EXTS = ('.png', '.mp4', '.avi', '.mov', '.mkv')


class ArchiveDB:
    DB_NAME = "archive.db"
    THUMBNAILS_DIR = "thumbnails"
    THUMB_VERSION = "v3"
    TABLE_NAME = "archive_items"
    SCHEMA_VERSION = 2

    def __init__(self, app_dir: str):
        self.db_path = os.path.join(app_dir, self.DB_NAME)
        self.thumbnails_dir_path = os.path.join(app_dir, self.THUMBNAILS_DIR)
        os.makedirs(self.thumbnails_dir_path, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ schema

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        schema_version = self._get_schema_version(cursor)
        if schema_version < self.SCHEMA_VERSION:
            self._migrate_schema(cursor, schema_version)
            cursor.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        conn.commit()
        conn.close()

    def _get_schema_version(self, cursor):
        cursor.execute("PRAGMA user_version")
        return cursor.fetchone()[0]

    def _migrate_schema(self, cursor, current_version):
        log.info("Migrating schema from v%s to v%s", current_version, self.SCHEMA_VERSION)
        if current_version == 0:
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME}_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rel_path TEXT NOT NULL UNIQUE,
                    item_type TEXT NOT NULL CHECK(item_type IN ('screenshot', 'recording')),
                    camera_index INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    size_bytes INTEGER,
                    duration_sec REAL DEFAULT NULL,
                    tags TEXT DEFAULT NULL,
                    thumbnail_path TEXT DEFAULT NULL
                )
            ''')
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (self.TABLE_NAME,))
            if cursor.fetchone():
                try:
                    cursor.execute(f"PRAGMA table_info({self.TABLE_NAME})")
                    old_columns = [info[1] for info in cursor.fetchall()]
                    if 'full_path' in old_columns:
                        cursor.execute(
                            f"SELECT full_path, item_type, camera_index, timestamp, size_bytes, "
                            f"duration_sec, tags, thumbnail_path FROM {self.TABLE_NAME}")
                        for row in cursor.fetchall():
                            full_path_str, item_type, cam_idx, ts, sz, dur, tags_json, thumb_path = row
                            rel_path_guess = os.path.basename(full_path_str)
                            try:
                                cursor.execute(f'''
                                    INSERT INTO {self.TABLE_NAME}_new
                                    (rel_path, item_type, camera_index, timestamp, size_bytes, duration_sec, tags, thumbnail_path)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (rel_path_guess, item_type, cam_idx, ts, sz, dur, tags_json, thumb_path))
                            except sqlite3.IntegrityError:
                                log.info("Duplicate rel_path %s during migration, skipped", rel_path_guess)
                except sqlite3.OperationalError as e:
                    log.error("Migration query failed: %s", e)
            cursor.execute(f"DROP TABLE IF EXISTS {self.TABLE_NAME}")
            cursor.execute(f"ALTER TABLE {self.TABLE_NAME}_new RENAME TO {self.TABLE_NAME}")
            current_version = 1
        if current_version == 1:
            # v1 -> v2: structure already matches v2
            pass
        log.info("Schema migration complete")

    # ------------------------------------------------------------------ helpers

    def _get_item_type_and_camera(self, filename: str):
        """Derive item_type and camera_index from filename pattern."""
        if filename.startswith("cam1_"):
            return ("screenshot" if filename.endswith(".png") else "recording"), 0
        if filename.startswith("cam2_"):
            return ("screenshot" if filename.endswith(".png") else "recording"), 1
        if filename.startswith(("split_", "edit_")):
            return "recording", 2
        return ("screenshot" if filename.endswith(".png") else "recording"), 0

    def thumb_abs(self, stored: str) -> str:
        """Resolve stored thumbnail reference to an existing absolute path.

        New rows store the basename; legacy rows may store absolute paths.
        """
        if not stored:
            return ""
        if os.path.isabs(stored):
            return stored if os.path.exists(stored) else ""
        candidate = os.path.join(self.thumbnails_dir_path, stored)
        return candidate if os.path.exists(candidate) else ""

    def _full_path(self, rel_path: str, item_type: str, base_dirs: dict) -> str:
        if item_type == 'screenshot':
            return os.path.join(base_dirs.get('screenshot', ''), rel_path)
        if item_type == 'recording':
            return os.path.join(base_dirs.get('recording', ''), rel_path)
        return ""

    # ------------------------------------------------------------------ content

    def _generate_thumbnail(self, full_path: str, item_type: str) -> str:
        """High-quality 16:9 thumbnail (480x270, q85).

        Recordings: grab a frame at ~15% of the timeline (first frames are
        often black during RTSP startup). 640x360 16:9 for crisp HiDPI cards.
        """
        if not PIL_OK:
            return ""
        stem = Path(full_path).stem
        thumb_filename = f"{stem}_thumb_{self.THUMB_VERSION}.jpg"
        thumb_full_path = os.path.join(self.thumbnails_dir_path, thumb_filename)
        img = None
        if item_type == "recording" and CV2_OK:
            try:
                cap = cv2.VideoCapture(full_path)
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                seek = int(min(max(1.0, n * 0.15), fps * 2.0)) if n else 1
                cap.set(cv2.CAP_PROP_POS_FRAMES, seek)
                ok, fr = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, fr = cap.read()
                cap.release()
                if ok:
                    img = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            except Exception as e:
                log.info("cv2 thumb frame failed for %s: %s", full_path, e)
        if img is None:
            try:
                img = Image.open(full_path)
            except Exception as e:
                log.info("PIL thumb failed for %s: %s", full_path, e)
                return ""
        try:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            # center-crop to 16:9, then resize to 480x270
            tw, th = 640, 360
            w, h = img.size
            target = tw / th
            cur = w / h
            if cur > target:
                nw = int(h * target)
                x0 = (w - nw) // 2
                img = img.crop((x0, 0, x0 + nw, h))
            elif cur < target:
                nh = int(w / target)
                y0 = (h - nh) // 2
                img = img.crop((0, y0, w, y0 + nh))
            img = img.resize((tw, th), Image.LANCZOS)
            img.save(thumb_full_path, "JPEG", quality=85)
            return thumb_filename
        except Exception as e:
            log.info("Thumbnail save failed for %s: %s", full_path, e)
            return ""

    def _video_duration(self, abs_path: str):
        if not CV2_OK:
            return None
        try:
            cap = cv2.VideoCapture(abs_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            if fps > 0 and frame_count > 0:
                return frame_count / fps
        except Exception as e:
            log.info("Duration probe failed for %s: %s", abs_path, e)
        return None

    def add_item_by_abs_path(self, abs_path: str, base_dirs: dict):
        abs_path_obj = Path(abs_path)
        rel_path = None
        item_type = None
        for typ, base_dir in base_dirs.items():
            base_path_obj = Path(base_dir)
            try:
                rel_path = str(abs_path_obj.relative_to(base_path_obj))
                derived_type, camera_index = self._get_item_type_and_camera(abs_path_obj.name)
                if typ != derived_type:
                    log.info("Type mismatch for %s (dir=%s, derived=%s), skipped", abs_path, typ, derived_type)
                    return
                item_type = derived_type
                break
            except ValueError:
                continue
        if not rel_path or not item_type:
            log.info("Path %s is outside configured base dirs, skipped", abs_path)
            return

        duration_sec = None
        if item_type == "recording" and CV2_OK:
            duration_sec = self._video_duration(str(abs_path_obj))
        thumbnail_path = self._generate_thumbnail(str(abs_path_obj), item_type)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(f'''
                INSERT INTO {self.TABLE_NAME}
                (rel_path, item_type, camera_index, timestamp, size_bytes, duration_sec, tags, thumbnail_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rel_path) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    size_bytes=excluded.size_bytes,
                    duration_sec=excluded.duration_sec,
                    thumbnail_path=excluded.thumbnail_path
            ''', (
                rel_path, item_type, camera_index, abs_path_obj.stat().st_mtime,
                abs_path_obj.stat().st_size, duration_sec, None, thumbnail_path
            ))
            conn.commit()
            log.info("Archived: %s", rel_path)
        except Exception as e:
            log.error("Failed to add item %s: %s", rel_path, e)
        finally:
            conn.close()

    def sync_with_directories(self, base_dirs: dict):
        """Scan base directories and add any new files to the archive DB."""
        found = 0
        for typ, base_dir in base_dirs.items():
            if not os.path.isdir(base_dir):
                continue
            for root, _, files in os.walk(base_dir):
                for file in files:
                    if file.lower().endswith(VIDEO_EXTS) and not file.startswith('.'):
                        abs_path = os.path.join(root, file)
                        rel_path_candidate = os.path.relpath(abs_path, base_dir)
                        if not self._item_exists_by_rel_path(rel_path_candidate):
                            self.add_item_by_abs_path(abs_path, base_dirs)
                            found += 1
        if found:
            log.info("Sync added %d new items", found)

    # ------------------------------------------------------- backfill / migrate

    def _video_codec(self, abs_path: str) -> str:
        return probe_codec(abs_path)

    def _transcode_to_h264(self, src_path: str) -> str:
        """Re-encode a non-H264 recording via ffmpeg; returns final path or ''."""
        if not ffmpeg_available():
            log.warning("ffmpeg unavailable, cannot convert %s", src_path)
            return ""
        ok, final_path = transcode_to_h264(src_path, log_ctx="archive backfill")
        return final_path if ok else ""

    def backfill_metadata(self, base_dirs: dict) -> None:
        """Complete archive rows: convert unplayable codecs (renaming .avi ->
        .mp4), fill durations, generate missing thumbnails. Runs in background.
        """
        if not CV2_OK and not PIL_OK:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"SELECT id, rel_path, item_type, thumbnail_path, duration_sec FROM {self.TABLE_NAME}")
            rows = cursor.fetchall()
            for row_id, rel_path, item_type, thumb_path, duration_sec in rows:
                full_path = self._full_path(rel_path, item_type, base_dirs)
                if not full_path or not os.path.exists(full_path):
                    continue
                updates = {}
                new_rel_path = None
                if item_type == "recording":
                    # normalize: convert unplayable codecs and fix misleading
                    # extensions (h264-content-named-.avi breaks cv2 demuxer)
                    converted = self._transcode_to_h264(full_path)
                    if converted and converted != full_path:
                        new_rel_path = os.path.basename(converted)
                        full_path = converted
                if item_type == "recording" and duration_sec is None and "duration_sec" not in updates:
                    updates["duration_sec"] = self._video_duration(full_path)
                needs_thumb = (not thumb_path or not self.thumb_abs(thumb_path)
                               or f"_{self.THUMB_VERSION}" not in os.path.basename(thumb_path))
                if needs_thumb:
                    generated = self._generate_thumbnail(full_path, item_type)
                    if generated:
                        updates["thumbnail_path"] = generated
                if updates or new_rel_path:
                    if new_rel_path and new_rel_path != rel_path:
                        updates["rel_path"] = new_rel_path
                    sets = ", ".join(f"{k} = ?" for k in updates)
                    try:
                        cursor.execute(
                            f"UPDATE {self.TABLE_NAME} SET {sets} WHERE id = ?",
                            (*updates.values(), row_id))
                        if new_rel_path and new_rel_path != rel_path:
                            log.info("Renamed archive row %s -> %s", rel_path, new_rel_path)
                        else:
                            log.info("Backfilled %s: %s", rel_path, ", ".join(updates))
                    except sqlite3.IntegrityError as e:
                        log.error("Backfill update failed for %s: %s", rel_path, e)
            conn.commit()
        except Exception as e:
            log.error("backfill_metadata failed: %s", e)
        finally:
            conn.close()

    def cleanup_missing(self, base_dirs: dict):
        """Remove DB rows whose files no longer exist on disk (C8)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        removed = 0
        try:
            cursor.execute(f"SELECT id, rel_path, item_type, thumbnail_path FROM {self.TABLE_NAME}")
            for row_id, rel_path, item_type, thumb_path in cursor.fetchall():
                full_path = self._full_path(rel_path, item_type, base_dirs)
                if full_path and not os.path.exists(full_path):
                    thumb_abs = self.thumb_abs(thumb_path)
                    if thumb_abs:
                        try:
                            os.remove(thumb_abs)
                        except OSError:
                            pass
                    cursor.execute(f"DELETE FROM {self.TABLE_NAME} WHERE id = ?", (row_id,))
                    removed += 1
            if removed:
                conn.commit()
                log.info("Cleanup removed %d stale items", removed)
        except Exception as e:
            log.error("cleanup_missing failed: %s", e)
        finally:
            conn.close()

    def _item_exists_by_rel_path(self, rel_path: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'SELECT 1 FROM {self.TABLE_NAME} WHERE rel_path = ?', (rel_path,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    # ------------------------------------------------------------------ queries

    def _rows_to_items(self, cursor, base_dirs: dict):
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        items = []
        for row in rows:
            item = dict(zip(columns, row))
            item['full_path'] = self._full_path(item['rel_path'], item['item_type'], base_dirs)
            item['thumbnail_path'] = self.thumb_abs(item.get('thumbnail_path'))
            if item['tags']:
                try:
                    item['tags'] = json.loads(item['tags'])
                except (json.JSONDecodeError, TypeError):
                    item['tags'] = []
            else:
                item['tags'] = []
            items.append(item)
        return items

    def get_all_items(self, base_dirs: dict) -> list:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM {self.TABLE_NAME} ORDER BY timestamp DESC')
        items = self._rows_to_items(cursor, base_dirs)
        conn.close()
        return items

    def remove_item(self, item_id: int, base_dirs: dict) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(f'SELECT rel_path, item_type, thumbnail_path FROM {self.TABLE_NAME} WHERE id = ?', (item_id,))
            result = cursor.fetchone()
            if not result:
                log.info("Item %s not found", item_id)
                return False
            rel_path, item_type, thumb_path = result
            full_path = self._full_path(rel_path, item_type, base_dirs)
            if not full_path:
                return False
            try:
                os.remove(full_path)
            except OSError as e:
                log.info("Could not remove file %s: %s", full_path, e)
            thumb_abs = self.thumb_abs(thumb_path)
            if thumb_abs:
                try:
                    os.remove(thumb_abs)
                except OSError as e:
                    log.info("Could not remove thumbnail %s: %s", thumb_abs, e)
            cursor.execute(f'DELETE FROM {self.TABLE_NAME} WHERE id = ?', (item_id,))
            conn.commit()
            log.info("Removed item %s (%s)", item_id, rel_path)
            return True
        except Exception as e:
            log.error("Failed to remove item %s: %s", item_id, e)
            return False
        finally:
            conn.close()

    def search_items(self, base_dirs: dict, search_term: str = "",
                     item_types: list = None, camera_indices: list = None) -> list:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE 1=1"
        params = []
        if search_term:
            query += " AND (rel_path LIKE ? OR tags LIKE ?)"
            term_param = f"%{search_term}%"
            params.extend([term_param, term_param])
        if item_types:
            placeholders = ",".join(["?" for _ in item_types])
            query += f" AND item_type IN ({placeholders})"
            params.extend(item_types)
        if camera_indices:
            placeholders = ",".join(["?" for _ in camera_indices])
            query += f" AND camera_index IN ({placeholders})"
            params.extend(camera_indices)
        query += " ORDER BY timestamp DESC"
        cursor.execute(query, params)
        items = self._rows_to_items(cursor, base_dirs)
        conn.close()
        return items
