import os
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
import json # 🌟 NUEVO IMPORT
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

# --- 🌟 EL NUEVO CEREBRO DE WEBSOCKETS (CON CHAT PRIVADO) ---
class ConnectionManager:
    def __init__(self):
        # Cambiamos de Lista a Diccionario: { "uid_del_usuario": WebSocket }
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, uid: str):
        await websocket.accept()
        self.active_connections[uid] = websocket

    def disconnect(self, uid: str):
        if uid in self.active_connections:
            del self.active_connections[uid]

    async def send_personal_message(self, message: str, uid: str):
        # Dispara el mensaje SOLO a la pantalla del usuario receptor
        if uid in self.active_connections:
            try:
                await self.active_connections[uid].send_text(message)
            except Exception:
                self.disconnect(uid)

    async def broadcast(self, message: str):
        # Mantenemos este para actualizar el mapa general
        for uid, connection in list(self.active_connections.items()):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(uid)

manager = ConnectionManager()

# 🌟 NUEVO: Ahora la ruta exige el UID del usuario (ej: /ws/UID_123)
@app.websocket("/ws/{uid}")
async def websocket_endpoint(websocket: WebSocket, uid: str):
    await manager.connect(websocket, uid)
    try:
        while True:
            data = await websocket.receive_text()
            
            # Filtramos pings y radares del mapa
            if data == "ping":
                continue
            elif data.startswith("request_loc|"):
                await manager.broadcast(data)
            else:
                # 🌟 LÓGICA DEL CHAT: Si llega un JSON, lo procesamos
                try:
                    payload = json.loads(data)
                    if payload.get("type") == "chat":
                        listing_id = payload["listing_id"]
                        receiver_id = payload["receiver_id"]
                        text = payload["text"]
                        msg_id = str(uuid.uuid4())
                        
                        # 1. Guardar en PostgreSQL (Fuente de verdad)
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO messages (id, listing_id, sender_id, text) VALUES (%s, %s, %s, %s)",
                            (msg_id, listing_id, uid, text)
                        )
                        conn.commit()
                        cursor.close()
                        conn.close()
                        
                        # 2. Rebotar el mensaje en vivo al receptor
                        mensaje_out = json.dumps({
                            "type": "chat",
                            "listing_id": listing_id,
                            "sender_id": uid,
                            "text": text
                        })
                        await manager.send_personal_message(mensaje_out, receiver_id)
                except Exception as e:
                    print(f"Error procesando mensaje socket: {e}")
                
    except WebSocketDisconnect:
        manager.disconnect(uid)

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
    email: str
    phone: str
    rut: str
    user_photo: Optional[str] = None
    created_at: Optional[str] = None

# Creamos el modelo para recibir la imagen
class ArrivalPhoto(BaseModel):
    photo_base64: str

class ChatMessage(BaseModel):
    id: Optional[str] = None
    listing_id: str
    sender_id: str
    text: str
    created_at: Optional[str] = None

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
                guardador_last_update TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                full_name TEXT,
                email TEXT,
                role TEXT,
                phone TEXT,
                rut TEXT,
                user_photo TEXT              
            )
        ''')

        # --- 🌟 NUEVO: TABLA DE MENSAJES PARA EL CHAT ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                listing_id TEXT,
                sender_id TEXT,
                text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

@app.get("/users")
def get_users():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if users:
        return {"status": "success", "data": users}
    return {"status": "error", "message": "Usuarios no encontrados"}

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

# --- 🌟 NUEVO: DESCARGAR HISTORIAL DE CHAT ---
@app.get("/chat/{listing_id}")
def get_chat_history(listing_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Ordenamos del más antiguo al más nuevo (ASC) para dibujar el chat correctamente
    cursor.execute('''
        SELECT id, listing_id, sender_id, text, created_at 
        FROM messages 
        WHERE listing_id = %s 
        ORDER BY created_at ASC
    ''', (listing_id,))
    
    mensajes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Convertimos las fechas nativas de SQL a texto ISO para evitar errores en Flutter
    for msg in mensajes:
        if msg['created_at']:
            msg['created_at'] = msg['created_at'].isoformat()
            
    return {"status": "success", "data": mensajes}

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
    
    # 1. Validación inicial rápida
    cursor.execute("SELECT status, user_id FROM listings WHERE id = %s", (listing_id,))
    result = cursor.fetchone()
    
    from fastapi import Response
    
    if not result: 
        conn.close()
        return Response(content='{"status": "error", "message": "No encontrada"}', status_code=404, media_type="application/json")
        
    if result[1] == req.client_id:
        conn.close()
        return Response(content='{"status": "error", "message": "No puedes contratar tu propia fila"}', status_code=400, media_type="application/json")

    # 2. 🌟 EL CANDADO ATÓMICO EN LA BASE DE DATOS
    # Exigimos estrictamente que el estado sea AVAILABLE en el mismo milisegundo de la escritura
    cursor.execute(
        "UPDATE listings SET status = 'BOOKED', client_id = %s WHERE id = %s AND status = 'AVAILABLE'", 
        (req.client_id, listing_id)
    )
    
    # 3. Verificamos si PostgreSQL realmente actualizó la fila
    filas_afectadas = cursor.rowcount
    
    if filas_afectadas == 0:
        # 🛑 Nadie fue actualizado. Alguien más ganó la carrera y tomó la fila primero.
        # Devolvemos un error 409 (Conflict) para que Flutter caiga en el bloque 'else'
        conn.close()
        return Response(content='{"status": "error", "message": "La fila ya fue tomada"}', status_code=409, media_type="application/json")
    
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

@app.post("/users")
def save_user(profile: UserProfile):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Usamos ON CONFLICT para que si el usuario ya existe, simplemente actualice sus datos
    cursor.execute('''
        INSERT INTO users (uid, role, full_name, email, phone, rut,  user_photo) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (uid) DO UPDATE 
        SET role = EXCLUDED.role,
            full_name = EXCLUDED.full_name, 
            email = EXCLUDED.email,
            phone = EXCLUDED.phone, 
            rut = EXCLUDED.rut,
            user_photo = EXCLUDED.user_photo
    ''', (profile.uid, profile.role, profile.full_name, profile.email, profile.phone, profile.rut, profile.user_photo))
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
    
    # 📢 MAGIA: Emitimos latitud, longitud Y la fecha exacta
    await manager.broadcast(f"loc|{listing_id}|{loc.lat}|{loc.lng}|{loc.guardador_last_update}")
    
    return {"status": "success"}

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