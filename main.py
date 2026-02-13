import sqlite3
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI()

# --- CONFIGURACIÓN DE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELO DE DATOS ---
class Listing(BaseModel):
    id: str = None
    title: str
    price: int
    lat: float
    lng: float
    status: str = "AVAILABLE" # AVAILABLE, BOOKED, COMPLETED

# --- BASE DE DATOS (SQLITE) ---
def init_db():
    """Crea la tabla si no existe"""
    conn = sqlite3.connect('fila_app.db')
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
    conn.close()

# Iniciamos la DB al arrancar el script
init_db()

# --- ENDPOINTS ---

@app.get("/")
def read_root():
    return {"message": "Servidor con Base de Datos SQLite 🚀"}

@app.get("/listings", response_model=List[Listing])
def get_listings():
    conn = sqlite3.connect('fila_app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM listings")
        rows = cursor.fetchall()
        
        # Imprimimos cuántas filas encontró para saber si lee la DB
        print(f"DEBUG: Se encontraron {len(rows)} filas en la DB")

        data = []
        for row in rows:
            # Convertimos manualmente para ver si falla alguna columna específica
            item = {
                "id": row["id"],
                "title": row["title"],
                "price": row["price"],
                "lat": row["lat"],
                "lng": row["lng"],
                "status": row["status"]
            }
            data.append(item)
            
        return data

    except Exception as e:
        # AQUÍ VEREMOS EL ERROR REAL
        print(f"🔥 ERROR CRÍTICO LEYENDO DB: {e}")
        # Importante: Imprimimos el tipo de error para saber si es SQL o Pydantic
        import traceback
        traceback.print_exc()
        return []
        
    finally:
        conn.close()

@app.post("/listings")
def create_listing(listing: Listing):
    listing.id = str(uuid.uuid4())
    
    conn = sqlite3.connect('fila_app.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO listings (id, title, price, lat, lng, status) VALUES (?, ?, ?, ?, ?, ?)",
        (listing.id, listing.title, listing.price, listing.lat, listing.lng, listing.status)
    )
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Guardado en DB", "id": listing.id}

@app.post("/book/{listing_id}")
def book_listing(listing_id: str):
    conn = sqlite3.connect('fila_app.db')
    cursor = conn.cursor()
    
    # 1. Verificar estado actual
    cursor.execute("SELECT status FROM listings WHERE id = ?", (listing_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return {"status": "error", "message": "Oferta no encontrada"}
    
    if result[0] != "AVAILABLE":
        conn.close()
        return {"status": "error", "message": "Ya está reservado o completado"}
    
    # 2. Actualizar a BOOKED
    cursor.execute("UPDATE listings SET status = 'BOOKED' WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "¡Contratado exitosamente!"}

@app.post("/complete/{listing_id}")
def complete_job(listing_id: str):
    conn = sqlite3.connect('fila_app.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM listings WHERE id = ?", (listing_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return {"status": "error", "message": "Código QR no válido"}
        
    if result[0] == "COMPLETED":
        conn.close()
        return {"status": "error", "message": "Este trabajo ya fue pagado anteriormente"}

    # Actualizar a COMPLETED
    cursor.execute("UPDATE listings SET status = 'COMPLETED' WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "¡Servicio validado! Pago liberado."}

# --- ENDPOINT PARA BORRAR (DELETE) ---
@app.delete("/listings/{listing_id}")
def delete_listing(listing_id: str):
    conn = sqlite3.connect('fila_app.db')
    cursor = conn.cursor()
    
    # Verificamos si existe
    cursor.execute("SELECT id FROM listings WHERE id = ?", (listing_id,))
    if not cursor.fetchone():
        conn.close()
        return {"status": "error", "message": "No existe esa oferta"}

    # Borramos
    cursor.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Oferta eliminada"}

