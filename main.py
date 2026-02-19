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

# --- MODELO DE DATOS ---
# Agregamos los 3 campos nuevos. 
# Les ponemos "= None" para que si hay filas antiguas en la BD sin estos datos, el GET /listings no explote.
class Listing(BaseModel):
    id: str = None
    title: str
    price: int
    lat: float
    lng: float
    status: str = "AVAILABLE"
    user_id: str = None
    user_name: str = None
    user_photo: str = None

# --- CONEXIÓN A BASE DE DATOS (POSTGRESQL) ---
def get_db_connection():
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
    return conn

def init_db():
    """Crea la tabla si no existe"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Actualizamos la creación de la tabla para incluir los campos nuevos
        # en caso de que se cree desde cero en el futuro.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT,
                price INTEGER,
                lat REAL,
                lng REAL,
                status TEXT,
                user_id TEXT,
                user_name TEXT,
                user_photo TEXT
            )
        ''')
        
        # Opcional pero seguro: Intentamos agregar las columnas por si la tabla ya existe 
        # y no las ejecutaste manualmente en Neon. Si ya existen, dará un pequeño error que ignoramos.
        try:
            cursor.execute('ALTER TABLE listings ADD COLUMN user_id TEXT;')
            cursor.execute('ALTER TABLE listings ADD COLUMN user_name TEXT;')
            cursor.execute('ALTER TABLE listings ADD COLUMN user_photo TEXT;')
        except:
            pass # Si la columna ya existe, fallará silenciosamente, lo cual está bien.
            
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Base de datos inicializada correctamente")
    except Exception as e:
        print(f"Error iniciando DB: {e}")

# Iniciamos la DB al arrancar
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
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT * FROM listings")
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"Error DB en GET /listings: {e}")
        return []

@app.post("/listings")
def create_listing(listing: Listing):
    listing.id = str(uuid.uuid4())
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Insertamos los 9 valores exactos que definimos en el modelo
    cursor.execute(
        """
        INSERT INTO listings (id, title, price, lat, lng, status, user_id, user_name, user_photo) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (listing.id, listing.title, listing.price, listing.lat, listing.lng, listing.status, listing.user_id, listing.user_name, listing.user_photo)
    )
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"status": "success", "message": "Guardado en Postgres", "id": listing.id}

@app.post("/book/{listing_id}")
def book_listing(listing_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM listings WHERE id = %s", (listing_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return {"status": "error", "message": "Oferta no encontrada"}
    
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

# Fin...