from flask import Flask, render_template, request, jsonify
import sqlite3
import datetime

DB_PATH = "hainyu.db"

app = Flask(__name__)


# ===== DBまわり =====

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """最初に一度だけ呼び出してテーブルを作成"""
    conn = get_db()
    cur = conn.cursor()

    # ヘッダー情報（搬入番号ごとの基本情報）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hainyu_headers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            hainyu_id    TEXT UNIQUE,
            date         TEXT,
            shipper      TEXT,
            dest         TEXT,
            item_name    TEXT,
            mark         TEXT,
            last_updated TEXT
        )
        """
    )

    # 明細行
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hainyu_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            hainyu_id    TEXT,
            row_index    INTEGER,
            package_type TEXT,
            qty          REAL,
            no_from      REAL,
            no_to        REAL,
            L            REAL,
            W            REAL,
            H            REAL,
            weight_kg    REAL,
            m3           REAL
        )
        """
    )

    conn.commit()
    conn.close()


# Flask 3.x では before_first_request が無いので、起動時に実行
init_db()


# ===== 画面ルーティング =====

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/edit")
def edit_page():
    return render_template("edit.html")


@app.route("/mobile-edit")
def mobile_edit_page():
    return render_template("mobile_edit.html")


@app.route("/report")
def report_page():
    return render_template("report.html")


@app.route("/search")
def search_page():
    return render_template("search.html")


# ===== API: 搬入番号ごとのデータ取得 =====

@app.get("/api/hainyu/<hainyu_id>")
def get_hainyu(hainyu_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM hainyu_headers WHERE hainyu_id = ?",
        (hainyu_id,),
    )
    header_row = cur.fetchone()
    if not header_row:
        conn.close()
        return jsonify({"error": "not found"}), 404

    cur.execute(
        "SELECT * FROM hainyu_items WHERE hainyu_id = ? ORDER BY row_index",
        (hainyu_id,),
    )
    item_rows = cur.fetchall()
    conn.close()

    header = {
        "date": header_row["date"],
        "shipper": header_row["shipper"],
        "dest": header_row["dest"],
        "itemName": header_row["item_name"],
        "mark": header_row["mark"],
    }
    items = []
    for row in item_rows:
        items.append(
            {
                "packageType": row["package_type"],
                "qty": row["qty"],
                "noFrom": row["no_from"],
                "noTo": row["no_to"],
                "L": row["L"],
                "W": row["W"],
                "H": row["H"],
                "weightKg": row["weight_kg"],
                "m3": row["m3"],
            }
        )

    return jsonify(
        {
            "header": header,
            "items": items,
            "lastUpdated": header_row["last_updated"],
        }
    )


# ===== API: 搬入番号ごとのデータ保存 =====

@app.post("/api/hainyu/<hainyu_id>")
def save_hainyu(hainyu_id):
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "no data"}), 400

    header = payload.get("header") or {}
    items = payload.get("items") or []

    conn = get_db()
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()

    # ヘッダー upsert
    cur.execute(
        """
        INSERT INTO hainyu_headers
            (hainyu_id, date, shipper, dest, item_name, mark, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(hainyu_id) DO UPDATE SET
            date         = excluded.date,
            shipper      = excluded.shipper,
            dest         = excluded.dest,
            item_name    = excluded.item_name,
            mark         = excluded.mark,
            last_updated = excluded.last_updated
        """,
        (
            hainyu_id,
            header.get("date"),
            header.get("shipper", ""),
            header.get("dest", ""),
            header.get("itemName", ""),
            header.get("mark", ""),
            now,
        ),
    )

    # 既存の明細を一旦削除してから入れ直し
    cur.execute("DELETE FROM hainyu_items WHERE hainyu_id = ?", (hainyu_id,))
    for idx, item in enumerate(items):
        cur.execute(
            """
            INSERT INTO hainyu_items
                (hainyu_id, row_index, package_type, qty,
                 no_from, no_to, L, W, H, weight_kg, m3)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hainyu_id,
                idx,
                item.get("packageType", ""),
                item.get("qty"),
                item.get("noFrom"),
                item.get("noTo"),
                item.get("L"),
                item.get("W"),
                item.get("H"),
                item.get("weightKg"),
                item.get("m3"),
            ),
        )

    conn.commit()
    conn.close()

    return jsonify({"ok": True, "lastUpdated": now})


# ===== API: 検索 =====

@app.get("/api/search")
def search_hainyu():
    q = (request.args.get("q") or "").strip()

    conn = get_db()
    cur = conn.cursor()

    if q:
        like = f"%{q}%"
        cur.execute(
            """
            SELECT * FROM hainyu_headers
            WHERE hainyu_id LIKE ?
               OR shipper   LIKE ?
               OR dest      LIKE ?
               OR item_name LIKE ?
               OR mark      LIKE ?
            ORDER BY COALESCE(last_updated, date) DESC, hainyu_id DESC
            LIMIT 100
            """,
            (like, like, like, like, like),
        )
    else:
        cur.execute(
            """
            SELECT * FROM hainyu_headers
            ORDER BY COALESCE(last_updated, date) DESC, hainyu_id DESC
            LIMIT 100
            """
        )

    rows = cur.fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append(
            {
                "hainyuId": row["hainyu_id"],
                "date": row["date"],
                "shipper": row["shipper"],
                "dest": row["dest"],
                "itemName": row["item_name"],
                "lastUpdated": row["last_updated"],
            }
        )

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(debug=True)
