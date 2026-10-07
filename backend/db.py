import os
import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54402/pvivscan")


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS iv_scans (
    id serial PRIMARY KEY,
    string_code text NOT NULL,
    voc_v double precision NOT NULL,
    isc_a double precision NOT NULL,
    fill_factor double precision NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    verdict text,
    reason text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    processed_at timestamptz
);
CREATE OR REPLACE FUNCTION notify_iv_scan() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('iv_scan_new', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_iv_scan_notify ON iv_scans;
CREATE TRIGGER trg_iv_scan_notify
AFTER INSERT ON iv_scans
FOR EACH ROW EXECUTE FUNCTION notify_iv_scan();

-- 黄金窗：逆变器启动时刻只在首次启动时钉一次，重启不重开。
CREATE TABLE IF NOT EXISTS app_meta (
    meta_key text PRIMARY KEY,
    meta_value timestamptz NOT NULL
);

-- 曲线册：封存后独立留存，不随在途单办结而改变。
CREATE TABLE IF NOT EXISTS golden_albums (
    id serial PRIMARY KEY,
    window_name text NOT NULL,
    sealed_by text NOT NULL,
    sealed_at timestamptz NOT NULL,
    window_opened_at timestamptz NOT NULL,
    point_count integer NOT NULL
);
CREATE TABLE IF NOT EXISTS golden_album_points (
    id serial PRIMARY KEY,
    album_id integer NOT NULL REFERENCES golden_albums(id),
    scan_id integer NOT NULL,
    string_code text NOT NULL,
    voc_v double precision NOT NULL,
    isc_a double precision NOT NULL,
    fill_factor double precision NOT NULL,
    reading_created_at timestamptz NOT NULL,
    captured_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_golden_points_album ON golden_album_points(album_id);

-- 缺一边整页不算完工：没有点列的册不允许落库。
CREATE OR REPLACE FUNCTION golden_album_has_points() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM golden_album_points WHERE album_id = NEW.id) THEN
    RAISE EXCEPTION '曲线册 % 缺少点列，整页作废', NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_golden_album_points ON golden_albums;
CREATE CONSTRAINT TRIGGER trg_golden_album_points
AFTER INSERT ON golden_albums
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION golden_album_has_points();
"""
