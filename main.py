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
            # Escuchamos lo que envían los celulares
            data = await websocket.receive_text()
            
            # 🌟 NUEVO: Si recibimos una petición de radar, la rebotamos a todos los conectados
            if data.startswith("request_loc|"):
                await manager.broadcast(data)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- MODELOS ---
class Listing(BaseModel):
    id: Optional[str] = None
    title: str
    price: int
    lat: float
    lng: float
    description: Optional[str] = None
    service_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str = "AVAILABLE"
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_photo: Optional[str] = None
    client_id: Optional[str] = None
    arrival_photo: Optional[str] = None
    guardador_lat: Optional[float] = None
    guardador_lng: Optional[float] = None
    guardador_last_update: Optional[str] = None

class GuardadorLocation(BaseModel):
    lat: float
    lng: float
    guardador_last_update: Optional[str] = None

class BookRequest(BaseModel):
    client_id: str

class UserProfile(BaseModel):
    uid: str
    role: str  # 'SOLICITANTE' o 'GUARDADOR'
    full_name: str
    phone: str
    rut: str

# Creamos el modelo para recibir la imagen
class ArrivalPhoto(BaseModel):
    photo_base64: str

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
                title TEXT,
                price INTEGER,
                lat REAL,
                lng REAL,
                description TEXT,
                service_time TEXT,
                end_time TEXT,
                status TEXT,
                user_id TEXT,
                user_name TEXT,
                user_photo TEXT,
                client_id TEXT,
                arrival_photo TEXT,
                guardador_lat REAL,
                guardador_lng REAL,
                guardador_last_update TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                rut TEXT
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

@app.get("/listings/{listing_id}", response_model=Listing)
def get_single_listing(listing_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Buscamos solo la fila que el solicitante está pidiendo
    cursor.execute("SELECT * FROM listings WHERE id = %s", (listing_id,))
    row = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    from fastapi import HTTPException
    if row:
        return row
    raise HTTPException(status_code=404, detail="Fila no encontrada")

@app.post("/listings")
async def create_listing(listing: Listing): # <--- async
    listing.id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    # 🌟 NUEVO: Añadimos service_time a la consulta y a los valores (%s)
    cursor.execute(
        "INSERT INTO listings (id, title, price, lat, lng, description, service_time, end_time, status, user_id, user_name, user_photo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (listing.id, listing.title, listing.price, listing.lat, listing.lng, listing.description, listing.service_time, listing.end_time, listing.status, listing.user_id, listing.user_name, listing.user_photo)
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

# --- ENDPOINTS DE USUARIOS (KYC) ---

@app.get("/users/{uid}")
def get_user(uid: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE uid = %s", (uid,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        return {"status": "success", "data": user}
    return {"status": "error", "message": "Usuario no encontrado"}

@app.post("/users")
def save_user(profile: UserProfile):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Usamos ON CONFLICT para que si el usuario ya existe, simplemente actualice sus datos
    cursor.execute('''
        INSERT INTO users (uid, role, full_name, phone, rut) 
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (uid) DO UPDATE 
        SET role = EXCLUDED.role,
            full_name = EXCLUDED.full_name, 
            phone = EXCLUDED.phone, 
            rut = EXCLUDED.rut
    ''', (profile.uid, profile.role, profile.full_name, profile.phone, profile.rut))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Perfil guardado correctamente"}

# Nuevo endpoint para actualizar la foto de llegada
@app.put("/listings/{listing_id}/arrival")
def update_arrival_photo(listing_id: str, data: ArrivalPhoto):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE listings 
        SET arrival_photo = %s 
        WHERE id = %s
    ''', (data.photo_base64, listing_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Foto de llegada guardada exitosamente"}

@app.put("/listings/{listing_id}/location")
async def update_guardador_location(listing_id: str, loc: GuardadorLocation):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE listings 
        SET guardador_lat = %s, guardador_lng = %s, guardador_last_update = %s
        WHERE id = %s
    ''', (loc.lat, loc.lng, loc.guardador_last_update, listing_id))
    
    conn.commit()
    conn.close()
    
    # 📢 MAGIA: Emitimos un mensaje cifrado solo con las coordenadas (Sin colapsar la BD)
    await manager.broadcast(f"loc|{listing_id}|{loc.lat}|{loc.lng}")
    
    return {"status": "success"}