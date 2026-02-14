import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import io
import time
import sqlite3
import datetime

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================

# ¡PEGA TU CLAVE AQUÍ DENTRO DE LAS COMILLAS!
API_KEY = "AIzaSyDBTsVTGgj9Ne_vQ-wyr9WaT0Zmsfyavbo" 

st.set_page_config(page_title="Sistema Taller Pro", page_icon="🏭", layout="wide")

if "PEGA_TU_CLAVE" in API_KEY:
    st.error("⚠️ ERROR CRÍTICO: No has pegado tu API Key en el código.")
    st.stop()

genai.configure(api_key=API_KEY)

# ==========================================
# 🧠 2. DETECTOR AUTOMÁTICO DE MODELO (¡Vital!)
# ==========================================
def obtener_mejor_modelo():
    """Pregunta a Google qué modelos tienes y elige el mejor disponible"""
    try:
        modelos = genai.list_models()
        nombres = [m.name for m in modelos if 'generateContent' in m.supported_generation_methods]
        
        # Orden de preferencia (Del más rápido/nuevo al más viejo)
        prioridades = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-pro-vision'
        ]
        
        # 1. Buscar coincidencia exacta
        for p in prioridades:
            if p in nombres: return p
            
        # 2. Buscar cualquiera que sea "flash"
        for n in nombres:
            if 'flash' in n: return n
            
        # 3. Fallback: El primero que encuentre
        if nombres: return nombres[0]
        
        return 'models/gemini-1.5-flash' # Por defecto si todo falla
    except:
        return 'models/gemini-1.5-flash'

# Guardamos el nombre del modelo correcto al iniciar
MODELO_ACTUAL = obtener_mejor_modelo()

# ==========================================
# 🗄️ 3. BASE DE DATOS (SQLITE)
# ==========================================
def init_db():
    conn = sqlite3.connect('taller_data.db')
    c = conn.cursor()
    
    # Tabla Usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, rol TEXT)''')
    
    # Tabla Gastos
    c.execute('''CREATE TABLE IF NOT EXISTS gastos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  fecha TEXT, proveedor TEXT, producto TEXT, cantidad REAL, 
                  unidad TEXT, precio_unitario REAL, precio_total REAL, 
                  usuario TEXT, fecha_carga TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Usuario Admin por defecto
    c.execute("INSERT OR IGNORE INTO usuarios VALUES ('admin', 'admin123', 'gerente')")
    
    conn.commit()
    conn.close()

def guardar_item_db(item, usuario):
    conn = sqlite3.connect('taller_data.db')
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO gastos (fecha, proveedor, producto, cantidad, unidad, precio_unitario, precio_total, usuario)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                  (item['Fecha'], item['Proveedor'], item['Producto'], item['Cantidad'], 
                   item['Unidad'], item['Precio Unitario'], item['Precio Total'], usuario))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Error guardando en BD: {e}")
        return False
    finally:
        conn.close()

def obtener_reporte_db(usuario, filtro=None):
    conn = sqlite3.connect('taller_data.db')
    query = "SELECT fecha, proveedor, producto, cantidad, unidad, precio_unitario, precio_total FROM gastos"
    if filtro:
        query += f" WHERE producto LIKE '%{filtro}%' OR proveedor LIKE '%{filtro}%'"
    query += " ORDER BY fecha DESC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

init_db()

# ==========================================
# 🔍 4. PROCESAMIENTO IA
# ==========================================
def analizar_documento(archivo_bytes, mime_type):
    # Usamos la variable global MODELO_ACTUAL que detectamos al principio
    model = genai.GenerativeModel(MODELO_ACTUAL)
    
    prompt = """
    Analiza esta factura de taller. Extrae los items.
    
    INSTRUCCIONES:
    1. Mantén precios y cantidades como NÚMEROS (floats).
    2. Devuelve SOLO JSON válido.
    
    ESTRUCTURA:
    {
        "fecha_compra": "YYYY-MM-DD", 
        "proveedor": "Nombre Empresa",
        "items": [
            {
                "producto": "Descripción",
                "cantidad": 0.0,
                "unidad": "uni/kg/lt",
                "precio_unitario": 0.0,
                "precio_total": 0.0
            }
        ]
    }
    """
    try:
        response = model.generate_content([prompt, {"mime_type": mime_type, "data": archivo_bytes}])
        texto = response.text
        # Limpieza
        texto_limpio = texto.replace("```json", "").replace("```", "").strip()
        inicio = texto_limpio.find('{')
        fin = texto_limpio.rfind('}') + 1
        
        if inicio != -1 and fin != -1:
            return json.loads(texto_limpio[inicio:fin])
        else:
            st.error(f"❌ Error de lectura IA. Respuesta:\n{texto}")
            return None
    except Exception as e:
        st.error(f"❌ Error de Conexión: {str(e)}")
        return None

# ==========================================
# 🔐 5. LOGIN Y UI
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

def check_login(u, p):
    conn = sqlite3.connect('taller_data.db')
    res = conn.cursor().execute("SELECT * FROM usuarios WHERE username = ? AND password = ?", (u, p)).fetchone()
    conn.close()
    return res is not None

# --- PANTALLA LOGIN ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🔐 Acceso Taller")
        # Mostramos qué modelo se detectó para estar seguros
        st.caption(f"🤖 Motor IA detectado: {MODELO_ACTUAL}") 
        
        u = st.text_input("Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.button("Ingresar", type="primary", use_container_width=True):
            if check_login(u, p):
                st.session_state.logged_in = True
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Datos incorrectos. (Prueba: admin / admin123)")

# --- PANTALLA SISTEMA ---
else:
    with st.sidebar:
        st.success(f"👤 {st.session_state.user}")
        if st.button("Cerrar Sesión"):
            st.session_state.logged_in = False
            st.rerun()
        st.divider()
        menu = st.radio("Navegación", ["📥 Cargar Facturas", "📊 Historial y Precios"])

    if menu == "📥 Cargar Facturas":
        st.title("📥 Cargar Compras")
        archivos = st.file_uploader("Sube facturas", type=["pdf", "png", "jpg"], accept_multiple_files=True)
        
        if archivos and st.button("Procesar Archivos", type="primary"):
            bar = st.progress(0)
            total = 0
            for i, arch in enumerate(archivos):
                bar.progress((i+1)/len(archivos))
                datos = analizar_documento(arch.getvalue(), arch.type)
                
                if datos and "items" in datos:
                    fecha = datos.get("fecha_compra", str(datetime.date.today()))
                    prov = datos.get("proveedor", "Sin Proveedor")
                    for item in datos["items"]:
                        item_db = {
                            "Fecha": fecha, "Proveedor": prov,
                            "Producto": item.get("producto", "Item"),
                            "Cantidad": float(item.get("cantidad", 0)),
                            "Unidad": item.get("unidad", "u"),
                            "Precio Unitario": float(item.get("precio_unitario", 0)),
                            "Precio Total": float(item.get("precio_total", 0))
                        }
                        if guardar_item_db(item_db, st.session_state.user): total += 1
                time.sleep(1)
            
            if total > 0: st.success(f"✅ Se guardaron {total} items.")
            else: st.warning("No se encontraron items.")

    elif menu == "📊 Historial y Precios":
        st.title("📊 Historial")
        filtro = st.text_input("🔍 Buscar repuesto...")
        df = obtener_reporte_db(st.session_state.user, filtro)
        
        if not df.empty:
            st.dataframe(
                df, 
                column_config={
                    "precio_total": st.column_config.NumberColumn("Total", format="$ %.2f"),
                    "precio_unitario": st.column_config.NumberColumn("Unitario", format="$ %.2f"),
                    "fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"),
                }, 
                use_container_width=True
            )
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 Excel", buffer, "historial.xlsx")
        else:
            st.info("Sin datos.")