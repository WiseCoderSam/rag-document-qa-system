import os
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Initialize the Gemini API client if the key is provided
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def get_embedding(text: str) -> list[float]:
    """
    Generate text embeddings using Google's text-embedding-004.
    If no API key is set, returns a list of zeros for mock testing.
    """
    if not GEMINI_API_KEY:
        # Mock embedding of size 768 (dimension size of text-embedding-004)
        return [0.0] * 768
        
    try:
        response = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_document"
        )
        return response["embedding"]
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return [0.0] * 768

def generate_chat_response(prompt: str, context: str = "") -> str:
    """
    Generate a response from Gemini using gemini-1.5-flash.
    """
    if not GEMINI_API_KEY:
        return "Gemini API Key is not configured. Please set the GEMINI_API_KEY environment variable to enable AI investigations."
        
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=(
                "You are an expert Security Operations Center (SOC) analyst. Your task is to investigate logs, "
                "summarize threats, map suspicious behavior to MITRE ATT&CK techniques, and answer user investigation queries "
                "based on the provided log context."
            )
        )
        
        full_content = prompt
        if context:
            full_content = f"Log context for investigation:\n---\n{context}\n---\n\nUser Question: {prompt}"
            
        response = model.generate_content(
            full_content,
            generation_config={"temperature": 0.2}
        )
        return response.text
    except Exception as e:
        return f"Error communicating with Gemini API: {e}"
