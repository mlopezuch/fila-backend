import os
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 🌟 EL MEGÁFONO DE WEBSOCKETS ---
class ConnectionManager:
    def __init__(self):
        # Aquí guardamos a todos los usuarios que tienen la app abierta
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # Le enviamos el mensaje a todos los conectados
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

# Endpoint al que se conecta el celular al abrir el mapa
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Mantenemos el tubo abierto escuchando
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- MODELOS ---
class Listing(BaseModel):
    id: Optional[str] = None
    title: str
    price: int
    lat: float
    lng: float
    status: str = "AVAILABLE"
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_photo: Optional[str] = None
    client_id: Optional[str] = None

class BookRequest(BaseModel):
    client_id: str

# --- BASE DE DATOS ---
def get_db_connection():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT, price INTEGER, lat REAL, lng REAL, status TEXT,
                user_id TEXT, user_name TEXT, user_photo TEXT, client_id TEXT
            )
        ''')
        # ... (intentos de agregar columnas omitidos para brevedad, ya los tienes en Neon)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error DB: {e}")

if os.environ.get("DATABASE_URL"):
    init_db()

# --- ENDPOINTS (Ahora son async para usar el megáfono) ---

@app.get("/")
def read_root():
    return {"message": "Servidor con WebSockets 🚀"}

@app.get("/listings", response_model=List[Listing])
def get_listings():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM listings")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

@app.post("/listings")
async def create_listing(listing: Listing): # <--- async
    listing.id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO listings (id, title, price, lat, lng, status, user_id, user_name, user_photo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (listing.id, listing.title, listing.price, listing.lat, listing.lng, listing.status, listing.user_id, listing.user_name, listing.user_photo)
    )
    conn.commit()
    conn.close()
    
    # 📢 ¡AVISAMOS A TODOS QUE HAY UNA NUEVA FILA!
    await manager.broadcast("update")
    return {"status": "success", "id": listing.id}

@app.post("/book/{listing_id}")
async def book_listing(listing_id: str, req: BookRequest): # <--- async
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, user_id FROM listings WHERE id = %s", (listing_id,))
    result = cursor.fetchone()
    
    if not result: return {"status": "error", "message": "No encontrada"}
    if result[0] != "AVAILABLE": return {"status": "error", "message": "Ya está reservado"}
    
    from fastapi import Response
    if result[1] == req.client_id:
        return Response(content='{"status": "error", "message": "No puedes contratar tu propia fila"}', status_code=400, media_type="application/json")
    
    cursor.execute("UPDATE listings SET status = 'BOOKED', client_id = %s WHERE id = %s", (req.client_id, listing_id))
    conn.commit()
    conn.close()
    
    # 📢 ¡AVISAMOS A TODOS QUE EL PIN DEBE CAMBIAR DE COLOR!
    await manager.broadcast("update")
    return {"status": "success", "message": "Contratado"}

@app.post("/complete/{listing_id}")
async def complete_job(listing_id: str): # <--- async
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM listings WHERE id = %s", (listing_id,))
    result = cursor.fetchone()
    
    if not result: return {"status": "error", "message": "No válido"}
    if result[0] == "COMPLETED": return {"status": "error", "message": "Ya pagado"}

    cursor.execute("UPDATE listings SET status = 'COMPLETED' WHERE id = %s", (listing_id,))
    conn.commit()
    conn.close()
    
    # 📢 ¡AVISAMOS A TODOS QUE EL TRABAJO TERMINÓ!
    await manager.broadcast("update")
    return {"status": "success", "message": "Validado"}

@app.delete("/listings/{listing_id}")
async def delete_listing(listing_id: str): # <--- async
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM listings WHERE id = %s", (listing_id,))
    conn.commit()
    conn.close()
    
    # 📢 ¡AVISAMOS A TODOS QUE UN PIN DESAPARECIÓ!
    await manager.broadcast("update")
    return {"status": "success", "message": "Eliminada"}