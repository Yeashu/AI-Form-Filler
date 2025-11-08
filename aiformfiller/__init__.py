"""AIFormFiller package."""

from .models import DetectedField
from .parser import extract_fields
from .filler import fill_pdf
from .llm import (
	ConversationState,
	configure_gemini,
	create_conversation,
	get_conversation_summary,
	get_next_question,
	process_user_response,
	reset_conversation,
	validate_and_format_with_gemini,
)
from models.conversation_state import ConversationState as FormConversationState
from services.field_detector import DetectedField as HtmlDetectedField, FieldDetector
from services.html_extractor import HTMLExtractor
from services.html_filler import HTMLFiller
from services.pipeline import FormPipeline, FormExtractionResult

__all__ = [
	"DetectedField",
	"extract_fields",
	"fill_pdf",
	"ConversationState",
	"FormConversationState",
	"configure_gemini",
	"create_conversation",
	"get_conversation_summary",
	"get_next_question",
	"process_user_response",
	"reset_conversation",
	"validate_and_format_with_gemini",
	"HTMLExtractor",
	"FieldDetector",
	"HtmlDetectedField",
	"HTMLFiller",
	"FormPipeline",
	"FormExtractionResult",
]
