import os
import sqlite3
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "hainyu.db")


# ===== DB 初期化 =====

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ヘッダー情報テーブル
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hainyu_headers (
            hainyu_id   TEXT PRIMARY KEY,
            date        TEXT,
            shipper     TEXT,
            dest        TEXT,
            item_name   TEXT,
            mark        TEXT
        )
        """
    )

    # 明細テーブル
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hainyu_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            hainyu_id    TEXT,
            package_type TEXT,
            no_from      INTEGER,
            no_to        INTEGER,
            qty          INTEGER,
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


# モジュール読み込み時に一度だけ実行
init_db()


def get_db():
    """毎回新しいコネクションを返す簡易版"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ===== ページ =====

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


# ===== API: 搬入データ 取得 =====

@app.route("/api/hainyu/<hainyu_id>", methods=["GET"])
def api_get_hainyu(hainyu_id):
    conn = get_db()
    cur = conn.cursor()

    # ヘッダー
    cur.execute(
        """
        SELECT
            hainyu_id,
            date,
            shipper,
            dest,
            item_name,
            mark
        FROM hainyu_headers
        WHERE hainyu_id = ?
        """,
        (hainyu_id,),
    )
    header_row = cur.fetchone()

    if not header_row:
        conn.close()
        return jsonify({"error": "not found"}), 404

    # 明細
    cur.execute(
        """
        SELECT
            id,
            package_type,
            no_from,
            no_to,
            qty,
            L,
            W,
            H,
            weight_kg,
            m3
        FROM hainyu_items
        WHERE hainyu_id = ?
        ORDER BY id
        """,
        (hainyu_id,),
    )
    rows = cur.fetchall()
    conn.close()

    header = {
        "hainyu_id": header_row["hainyu_id"],
        "date": header_row["date"],
        "shipper": header_row["shipper"],
        "dest": header_row["dest"],
        "itemName": header_row["item_name"],
        "mark": header_row["mark"],
    }

    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "packageType": r["package_type"],
                "noFrom": r["no_from"],
                "noTo": r["no_to"],
                "qty": r["qty"],
                "L": r["L"],
                "W": r["W"],
                "H": r["H"],
                "weightKg": r["weight_kg"],
                "m3": r["m3"],
            }
        )

    return jsonify({"header": header, "items": items})


# ===== API: 搬入データ 登録 / 更新 =====

@app.route("/api/hainyu/<hainyu_id>", methods=["POST"])
def api_save_hainyu(hainyu_id):
    data = request.get_json(force=True)

    header = data.get("header") or {}
    items = data.get("items") or []

    date = header.get("date")
    shipper = header.get("shipper", "")
    dest = header.get("dest", "")
    item_name = header.get("itemName", "")
    mark = header.get("mark", "")

    conn = get_db()
    cur = conn.cursor()

    # ヘッダー upsert
    cur.execute(
        """
        INSERT INTO hainyu_headers (hainyu_id, date, shipper, dest, item_name, mark)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(hainyu_id) DO UPDATE SET
          date      = excluded.date,
          shipper   = excluded.shipper,
          dest      = excluded.dest,
          item_name = excluded.item_name,
          mark      = excluded.mark
        """,
        (hainyu_id, date, shipper, dest, item_name, mark),
    )

    # 明細は一度削除してから挿入し直し
    cur.execute("DELETE FROM hainyu_items WHERE hainyu_id = ?", (hainyu_id,))

    for it in items:
        cur.execute(
            """
            INSERT INTO hainyu_items (
                hainyu_id,
                package_type,
                no_from,
                no_to,
                qty,
                L,
                W,
                H,
                weight_kg,
                m3
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hainyu_id,
                it.get("packageType"),
                it.get("noFrom"),
                it.get("noTo"),
                it.get("qty"),
                it.get("L"),
                it.get("W"),
                it.get("H"),
                it.get("weightKg"),
                it.get("m3"),
            ),
        )

    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


# ===== API: 検索 =====
# search.html 側は { "results": [...] } という形式を期待しているので、
# 必ず {"results": result} の形で返す。

@app.route("/api/search", methods=["GET"])
def api_search():
    q = request.args.get("q", "").strip()

    conn = get_db()
    cur = conn.cursor()

    base_sql = """
        SELECT
            hainyu_id,
            date,
            shipper,
            dest,
            item_name,
            mark
        FROM hainyu_headers
    """
    params = []

    if q:
        like = f"%{q}%"
        base_sql += """
            WHERE
                hainyu_id LIKE ?
                OR shipper LIKE ?
                OR dest LIKE ?
                OR item_name LIKE ?
                OR mark LIKE ?
        """
        params.extend([like, like, like, like, like])

    # q が空でも最近順で最大100件返す
    base_sql += " ORDER BY date DESC, hainyu_id ASC LIMIT 100"

    cur.execute(base_sql, params)
    rows = cur.fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append(
            {
                "hainyuId": r["hainyu_id"],
                "date": r["date"],
                "shipper": r["shipper"],
                "dest": r["dest"],
                "itemName": r["item_name"],
                # lastUpdated カラムはないので、とりあえず date を流用
                "lastUpdated": r["date"],
            }
        )

    return jsonify({"results": result})


if __name__ == "__main__":
    app.run(debug=True)
