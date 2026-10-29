from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from ollama import AsyncClient
from typing import Optional, List
import os

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
client = AsyncClient(host=OLLAMA_HOST)

app = FastAPI(title="Ollama Manager API")

class LoadModelRequest(BaseModel):
    model_name: str
    keep_alive: str = "1h"

class AskRequest(BaseModel):
    model_name: str
    prompt: str
    schema_name: str = "platform"
    keep_alive: str = "5m"

class UnloadRequest(BaseModel):
    model_name: str

class PlatformResponse(BaseModel):
    url: str = Field(description="Copia EXACTAMENTE la URL que aparece en el contexto. No inventes ni modifiques ninguna URL.")
    title: str = Field(
        description="Titular de la  plataforma, sin comillas ni puntuación final."
    )
    description: str = Field(
        description="Resumen del porque la plataforma es una opción valida de busqueda."
    )
    search_query: str = Field(
        description="Sugerencía de cadena de busqueda."
    )


AVAILABLE_SCHEMAS = {
    "platform": PlatformResponse,
}

@app.post("/models/load")
async def load_model(request: LoadModelRequest):
    try:
        response = await client.generate(
            model=request.model_name,
            prompt="", 
            keep_alive=request.keep_alive
        )
        return {
            "status": "success",
            "message": f"Modelo '{request.model_name}' cargado en memoria.",
            "keep_alive": request.keep_alive,
            "details": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cargar el modelo: {str(e)}")



@app.post("/models/ask")
async def ask_model(request: AskRequest):
    schema_class = AVAILABLE_SCHEMAS.get(schema_name)
    if not schema_class:
        raise HTTPException(400, detail=f"Esquema '{schema_name}' no encontrado")
    
    response = await client.chat(
        model=request.model_name,
        messages=[
            {"role": "system", "content": "Responde únicamente con un objeto JSON que cumpla el esquema proporcionado. No añadas texto adicional."},
            {"role": "user", "content": request.prompt}
        ],
        format=schema_class.model_json_schema(), 
        options={"temperature": 0},
        keep_alive=keep_alive
    )
    
    raw_content = response["message"]["content"]
    try:
        parsed = schema_class.model_validate_json(raw_content)
        return parsed.model_dump()  # Devuelve un dict limpio y validado
    except Exception as e:
        raise HTTPException(500, detail=f"El modelo no generó un JSON válido: {e}. Texto crudo: {raw_content}")


@app.post("/models/unload")
async def unload_model(request: UnloadRequest):
    try:
        await client.generate(
            model=request.model_name,
            prompt="",
            keep_alive=0
        )
        return {
            "status": "success",
            "message": f"Modelo '{request.model_name}' descargado de la memoria."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al descargar el modelo: {str(e)}")
