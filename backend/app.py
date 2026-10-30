from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
import urllib.request
import urllib.error
from pathlib import Path

app = Flask(__name__)
CORS(app)

DATABASE = Path(__file__).with_name("blockstock.db")

# Public MST Testnet configuration. No private keys are stored here.
MST_TESTNET_RPC = "https://testnetrpc.mstblockchain.com"
MST_TESTNET_CHAIN_ID = 91562037
BLOCKSTOCK_CONTRACT = "0xA3f0e936D6971D1e7962a3b726fbDc56D38aA49f"


def rpc_call(method, params=None):
    """Make a read-only JSON-RPC request to MST Testnet."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or []
    }).encode("utf-8")
    req = urllib.request.Request(
        MST_TESTNET_RPC,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("error"):
        raise RuntimeError(result["error"].get("message", "RPC error"))
    return result.get("result")


def connect_db():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                qty INTEGER NOT NULL DEFAULT 0 CHECK(qty >= 0),
                unit TEXT NOT NULL,
                cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0),
                reorder_level INTEGER NOT NULL DEFAULT 10 CHECK(reorder_level >= 0)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                material TEXT NOT NULL,
                qty INTEGER NOT NULL CHECK(qty > 0),
                unit TEXT NOT NULL,
                cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0),
                supplier TEXT DEFAULT '',
                recipient TEXT DEFAULT '',
                purpose TEXT DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                recorded_by TEXT DEFAULT '',
                approval TEXT NOT NULL DEFAULT 'Pending'
                    CHECK(approval IN ('Pending', 'Approved', 'Rejected')),
                notes TEXT DEFAULT '',
                reviewer TEXT DEFAULT '',
                review_reason TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS unique_inbound_reference
            ON transactions(reference COLLATE NOCASE)
            WHERE type = 'IN' AND reference != ''
        """)
        
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(transactions)").fetchall()
        }

        if "reviewer" not in columns:
            db.execute("ALTER TABLE transactions ADD COLUMN reviewer TEXT DEFAULT ''")

        if "review_reason" not in columns:
            db.execute("ALTER TABLE transactions ADD COLUMN review_reason TEXT DEFAULT ''")

               


def material_dict(row):
    item = dict(row)
    item["quantity"] = item["qty"]
    item["reorderLevel"] = item.pop("reorder_level")
    return item


def transaction_dict(row):
    item = dict(row)
    item["ref"] = item.pop("reference")
    item["time"] = item.pop("created_at")
    return item


def error(message, status):
    return jsonify({"error": message}), status


@app.route("/")
def home():
    return jsonify({"message": "BlockStock Backend is running"})


@app.route("/health")
def health():
    # Keep the existing health check while also reporting real RPC/contract status
    # in the shape expected by the current BlockStock frontend.
    response = {
        "status": "ok",
        "blockchain": {
            "connected": False,
            "network": "MST Testnet",
            "chainId": MST_TESTNET_CHAIN_ID,
            "contract": BLOCKSTOCK_CONTRACT,
            "txCount": 0
        }
    }
    try:
        chain_id_hex = rpc_call("eth_chainId")
        actual_chain_id = int(chain_id_hex, 16)
        if actual_chain_id != MST_TESTNET_CHAIN_ID:
            response["blockchain"]["error"] = (
                f"RPC returned chain ID {actual_chain_id}, expected "
                f"{MST_TESTNET_CHAIN_ID}"
            )
        else:
            bytecode = rpc_call("eth_getCode", [BLOCKSTOCK_CONTRACT, "latest"])
            if not bytecode or bytecode == "0x":
                response["blockchain"]["error"] = (
                    "No contract bytecode found at the configured address on MST Testnet."
                )
            else:
                response["blockchain"]["connected"] = True
                response["blockchain"]["contractCodeFound"] = True
    except Exception as exc:
        response["blockchain"]["error"] = str(exc)

    return jsonify(response)


@app.route("/inventory", methods=["GET"])
def get_inventory():
    with connect_db() as db:
        rows = db.execute("SELECT * FROM inventory ORDER BY name").fetchall()
    return jsonify([material_dict(row) for row in rows])


@app.route("/inventory", methods=["POST"])
def add_material():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    unit = str(data.get("unit", "")).strip()

    try:
        qty = int(data.get("qty", data.get("quantity", 0)))
        cost = float(data.get("cost", 0))
        reorder = int(data.get("reorderLevel", data.get("reorder_level", 10)))
    except (ValueError, TypeError):
        return error("Invalid numeric value", 400)

    if not name or not unit:
        return error("Name and unit are required", 400)
    if qty < 0 or cost < 0 or reorder < 0:
        return error("Values cannot be negative", 400)

    try:
        with connect_db() as db:
            cursor = db.execute("""
                INSERT INTO inventory (name, qty, unit, cost, reorder_level)
                VALUES (?, ?, ?, ?, ?)
            """, (name, qty, unit, cost, reorder))
            row = db.execute(
                "SELECT * FROM inventory WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return jsonify(material_dict(row)), 201
    except sqlite3.IntegrityError:
        return error("This material already exists", 409)


@app.route("/transactions", methods=["GET"])
def get_transactions():
    with connect_db() as db:
        rows = db.execute("SELECT * FROM transactions ORDER BY id DESC").fetchall()
    return jsonify([transaction_dict(row) for row in rows])


@app.route("/transactions", methods=["POST"])
def create_transaction():
    data = request.get_json(silent=True) or {}
    movement_type = str(data.get("type", "")).upper().strip()
    material = str(data.get("material", "")).strip()
    unit = str(data.get("unit", "")).strip()
    reference = str(data.get("ref", data.get("reference", ""))).strip()

    try:
        qty = int(data.get("qty", data.get("quantity", 0)))
        cost = float(data.get("cost", 0))
    except (ValueError, TypeError):
        return error("Invalid quantity or cost", 400)

    if movement_type not in ("IN", "OUT"):
        return error("Type must be IN or OUT", 400)
    if not material or not unit or qty <= 0 or cost < 0:
        return error("Valid material, unit, positive quantity and non-negative cost are required", 400)

    # New requests are always pending. The client cannot approve its own request.
    try:
        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute(
                "SELECT * FROM inventory WHERE name = ? COLLATE NOCASE",
                (material,)
            ).fetchone()

            if movement_type == "OUT" and not item:
                return error("Material does not exist", 404)
            if item and item["unit"].casefold() != unit.casefold():
                return error("Unit does not match inventory", 400)
            if movement_type == "IN" and reference:
                duplicate = db.execute("""
                    SELECT id FROM transactions
                    WHERE type = 'IN' AND reference = ? COLLATE NOCASE
                """, (reference,)).fetchone()
                if duplicate:
                    return error("Duplicate invoice reference", 409)

            cursor = db.execute("""
                INSERT INTO transactions (
                    type, material, qty, unit, cost, supplier, recipient,
                    purpose, reference, recorded_by, approval, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
            """, (
                movement_type, material, qty, unit, cost,
                str(data.get("supplier", "")),
                str(data.get("recipient", "")),
                str(data.get("purpose", "")),
                reference,
                str(data.get("user", data.get("recorded_by", ""))),
                str(data.get("notes", ""))
            ))
            row = db.execute(
                "SELECT * FROM transactions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()

        return jsonify(transaction_dict(row)), 201
    except sqlite3.IntegrityError:
        return error("Duplicate record or invalid database operation", 409)


def review_transaction(transaction_id, decision):
    data = request.get_json(silent=True) or {}
    reviewer = str(data.get("reviewer", "Workspace reviewer")).strip()
    reason = str(data.get("reason", data.get("notes", ""))).strip()

    try:
        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            tx = db.execute(
                "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            if not tx:
                return error("Transaction not found", 404)
            if tx["approval"] != "Pending":
                return error(f"Transaction is already {tx['approval'].lower()}", 409)

            if decision == "Approved":
                item = db.execute(
                    "SELECT * FROM inventory WHERE name = ? COLLATE NOCASE",
                    (tx["material"],)
                ).fetchone()

                if item and item["unit"].casefold() != tx["unit"].casefold():
                    return error("Unit does not match inventory", 400)

                if tx["type"] == "OUT":
                    if not item:
                        return error("Material does not exist", 404)
                    if tx["qty"] > item["qty"]:
                        return error("Insufficient stock to approve this transaction", 400)
                    db.execute(
                        "UPDATE inventory SET qty = qty - ? WHERE id = ?",
                        (tx["qty"], item["id"])
                    )
                else:
                    if item:
                        db.execute("""
                            UPDATE inventory SET qty = qty + ?, cost = ?
                            WHERE id = ?
                        """, (tx["qty"], tx["cost"], item["id"]))
                    else:
                        db.execute("""
                            INSERT INTO inventory (name, qty, unit, cost, reorder_level)
                            VALUES (?, ?, ?, ?, 10)
                        """, (tx["material"], tx["qty"], tx["unit"], tx["cost"]))

            db.execute("""
                UPDATE transactions
                SET approval = ?, reviewer = ?, review_reason = ?
                WHERE id = ?
            """, (decision, reviewer, reason, transaction_id))
            row = db.execute(
                "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()

        return jsonify(transaction_dict(row))
    except sqlite3.IntegrityError:
        return error("Database rejected this operation; check duplicate references and stock values", 409)


@app.route("/transactions/<int:transaction_id>/approve", methods=["POST"])
def approve_transaction(transaction_id):
    return review_transaction(transaction_id, "Approved")


@app.route("/transactions/<int:transaction_id>/reject", methods=["POST"])
def reject_transaction(transaction_id):
    return review_transaction(transaction_id, "Rejected")


# Initialize tables when the module is imported or run directly.
initialize_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
