"""API pública para cliente enviar mensagens via Evolution API.

Endpoints para o frontend /cliente fazer requisições de mensagem
em nome do cliente (não admin).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.agent.channels.evolution import EvolutionAdapter
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/client", tags=["evolution_client"])


class ClientMessageRequest(BaseModel):
    phone_number: str
    message: str


class ClientMessageResponse(BaseModel):
    status: str
    message_id: str | None = None
    error: str | None = None


@router.post("/send-message", response_model=ClientMessageResponse)
async def send_client_message(request: ClientMessageRequest) -> ClientMessageResponse:
    """Envia mensagem do cliente via Evolution API.

    Usado pelo frontend /cliente para conversar com o agente de WhatsApp.
    Requer que a instância Evolution já esteja pareada e rodando.
    """
    settings = get_settings()

    if not settings.evolution_api_url or not settings.evolution_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evolution API não configurada",
        )

    adapter = EvolutionAdapter(settings)

    try:
        await adapter.send_message(
            phone_number=request.phone_number,
            message=request.message,
        )
        return ClientMessageResponse(status="sent", message_id=None)
    except Exception as e:
        logger.exception("Falha ao enviar mensagem para %s", request.phone_number)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao enviar mensagem: {str(e)}",
        ) from e


@router.get("/instance-status")
async def get_instance_status() -> dict:
    """Retorna status da instância Evolution API (conectada, QR code se necessário)."""
    settings = get_settings()

    if not settings.evolution_api_url or not settings.evolution_api_key:
        return {
            "status": "not_configured",
            "message": "Evolution API não configurada",
        }

    try:
        async with httpx.AsyncClient() as client:
            # Checa se a instância existe e está conectada
            response = await client.get(
                f"{settings.evolution_api_url}/instance/fetch/{settings.evolution_instance}",
                headers={"apikey": settings.evolution_api_key},
                timeout=5.0,
            )

            if response.status_code == 200:
                data = response.json()
                # Evolution API retorna connectionStatus na resposta
                connection_status = data.get("instance", {}).get(
                    "connectionStatus", "unknown"
                )
                return {
                    "status": "connected" if connection_status == "open" else "disconnected",
                    "connection_status": connection_status,
                    "instance_name": settings.evolution_instance,
                }
            elif response.status_code == 404:
                # Instância não existe, precisa criar e parear QR code
                return {
                    "status": "not_paired",
                    "message": "Instância não encontrada. Use POST /instance/create para criar.",
                    "instance_name": settings.evolution_instance,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Evolution API retornou {response.status_code}",
                }
    except Exception as e:
        logger.exception("Falha ao verificar status da Evolution API")
        return {
            "status": "error",
            "message": str(e),
        }
