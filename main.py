import os
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI()

# --- CONFIGURACIÓN CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ListingCreate(BaseModel):
    title: str
    description: str
    price: int
    lat: float
    lng: float
    status: str = "AVAILABLE"
    # --- NUEVOS CAMPOS ---
    user_id: str
    user_name: str
    user_photo: str

# --- MODELO DE DATOS ---
class Listing(BaseModel):
    id: str = None
    title: str
    price: int
    lat: float
    lng: float
    status: str = "AVAILABLE"
    # --- NUEVOS CAMPOS ---
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_photo: Optional[str] = None
    created_at: datetime

# --- CONEXIÓN A BASE DE DATOS (POSTGRESQL) ---
def get_db_connection():
    # Render nos dará esta URL secreta en las variables de entorno
    # Si estás en tu PC y quieres probar, tienes que poner la URL de Neon aquí manualmente o usar variables de entorno
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
    return conn

def init_db():
    """Crea la tabla si no existe"""
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
                status TEXT
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Base de datos inicializada correctamente")
    except Exception as e:
        print(f"Error iniciando DB: {e}")

# Iniciamos la DB al arrancar (solo si tenemos la URL)
if os.environ.get("DATABASE_URL"):
    init_db()

# --- ENDPOINTS ---

@app.get("/")
def read_root():
    return {"message": "Servidor con PostgreSQL 🚀"}

@app.get("/listings", response_model=List[Listing])
def get_listings():
    try:
        conn = get_db_connection()
        # RealDictCursor hace que los resultados sean diccionarios (igual que antes)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT * FROM listings")
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"Error DB: {e}")
        return []

@app.post("/listings", response_model=Listing, status_code=201)
async def create_listing(listing: ListingCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # --- CONSULTA SQL ACTUALIZADA ---
    query = """
        INSERT INTO listings 
        (title, description, price, lat, lng, status, user_id, user_name, user_photo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, title, description, price, lat, lng, status, user_id, user_name, user_photo, created_at;
    """
    
    # Asegúrate de pasar los 9 valores en el orden correcto
    values = (
        listing.title, 
        listing.description, 
        listing.price, 
        listing.lat, 
        listing.lng, 
        listing.status,
        listing.user_id,    # Nuevo
        listing.user_name,  # Nuevo
        listing.user_photo  # Nuevo
    )
    
    cursor.execute(query, values)
    new_listing = cursor.fetchone()
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return new_listing

@app.post("/book/{listing_id}")
def book_listing(listing_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM listings WHERE id = %s", (listing_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return {"status": "error", "message": "Oferta no encontrada"}
    
    # En psycopg2, result es una tupla, accedemos con [0]
    if result[0] != "AVAILABLE":
        conn.close()
        return {"status": "error", "message": "Ya está reservado"}
    
    cursor.execute("UPDATE listings SET status = 'BOOKED' WHERE id = %s", (listing_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "¡Contratado exitosamente!"}

@app.post("/complete/{listing_id}")
def complete_job(listing_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM listings WHERE id = %s", (listing_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return {"status": "error", "message": "Código QR no válido"}
        
    if result[0] == "COMPLETED":
        conn.close()
        return {"status": "error", "message": "Este trabajo ya fue pagado"}

    cursor.execute("UPDATE listings SET status = 'COMPLETED' WHERE id = %s", (listing_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "¡Servicio validado! Pago liberado."}

@app.delete("/listings/{listing_id}")
def delete_listing(listing_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM listings WHERE id = %s", (listing_id,))
    if not cursor.fetchone():
        conn.close()
        return {"status": "error", "message": "No existe esa oferta"}

    cursor.execute("DELETE FROM listings WHERE id = %s", (listing_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Oferta eliminada"}

