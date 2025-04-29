#!/usr/bin/env python
"""
Test script for NotebookAgent with local Word documents.
This script demonstrates how to use NotebookAgent to process a Word document,
generate a summary, and create a narrated audio version.
"""
import os
import asyncio
import argparse
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import time
import signal
import webbrowser
import shutil

from navconfig import BASE_DIR
from parrot.bots.notebook import NotebookAgent
from parrot.models import AgentResponse


def serve_directory(directory, port=8000):
    """
    Create a simple HTTP server to serve files from a directory.
    
    Args:
        directory: Directory to serve files from
        port: Port to serve on
        
    Returns:
        The server instance and thread
    """
    os.chdir(directory)
    
    # Create server
    handler = SimpleHTTPRequestHandler
    httpd = HTTPServer(("", port), handler)
    
    # Start server in a separate thread
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    print(f"Server started at http://localhost:{port}")
    return httpd, server_thread


async def process_document(document_path, output_dir=None, voice_gender="FEMALE", port=8000):
    """
    Process a document with NotebookAgent
    
    Args:
        document_path: Path to the Word document
        output_dir: Directory to save output files
        voice_gender: Gender for the audio narration
        port: Port for the temporary server
    """
    # Validate document path
    document_path = Path(document_path).resolve()
    if not document_path.exists():
        print(f"Error: Document not found at {document_path}")
        return
    
    # Create a temporary directory to serve the file
    temp_dir = Path(BASE_DIR) / "temp_serve"
    temp_dir.mkdir(exist_ok=True)
    
    # Copy the document to the temporary directory
    temp_file = temp_dir / document_path.name
    shutil.copy2(document_path, temp_file)
    
    # Start a simple HTTP server
    server, thread = serve_directory(temp_dir, port)
    
    try:
        # Create URL to the document
        document_url = f"http://localhost:{port}/{document_path.name}"
        print(f"Document available at: {document_url}")
        
        # Configure output directory
        if output_dir:
            output_path = Path(output_dir).resolve()
        else:
            output_path = BASE_DIR / "static" / "output"
        
        output_path.mkdir(parents=True, exist_ok=True)
        print(f"Output will be saved to: {output_path}")
        
        # Initialize the NotebookAgent
        agent = NotebookAgent(
            name="Document Processor",
            llm="vertexai"  # Use VertexAI as the default LLM
        )
        
        # Configure the agent
        await agent.configure(document_url=document_url)
        
        print("\nAgent configured. Processing document...")
        
        # Añadir depuración después de cargar el documento
        print("\nDocument loaded, checking content...")
        if "_document_content" in dir(agent) and agent._document_content:
            content_preview = agent._document_content[:200] + "..." if len(agent._document_content) > 200 else agent._document_content
            print(f"Document content preview: {content_preview}")
            print(f"Document content length: {len(agent._document_content)} characters")
        else:
            print("No document content was loaded!")
        
        # Process the document
        result = await agent.process_document_workflow(document_url)
        
        # Debuggear el resultado
        print(f"\nWorkflow result keys: {result.keys()}")
        if "error" in result:
            print(f"Error in workflow: {result['error']}")
        
        # Print summary
        print("\n----- DOCUMENT SUMMARY -----")
        print(result["summary"])
        print("----- END SUMMARY -----\n")
        
        # Print audio file information
        audio_info = result.get("audio", {})
        if audio_info and "file_path" in audio_info:
            audio_path = audio_info["file_path"]
            print(f"Audio summary created at: {audio_path}")
            
            # Copy the audio file to the output directory if needed
            if output_dir:
                audio_filename = Path(audio_path).name
                output_audio = output_path / audio_filename
                shutil.copy2(audio_path, output_audio)
                print(f"Audio file copied to: {output_audio}")
        else:
            print("No audio summary was generated")
        
        return result
    
    finally:
        # Stop the server and clean up
        print("Shutting down server...")
        server.shutdown()
        
        # Clean up temporary files
        if temp_file.exists():
            temp_file.unlink()
        if temp_dir.exists():
            try:
                temp_dir.rmdir()
            except:
                pass


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Process a Word document with NotebookAgent")
    parser.add_argument("document_path", help="Path to the Word document")
    parser.add_argument("--output", "-o", help="Output directory for processed files")
    parser.add_argument("--voice", "-v", choices=["FEMALE", "MALE"], default="FEMALE", 
                        help="Voice gender for audio narration")
    parser.add_argument("--port", "-p", type=int, default=8000,
                        help="Port for the temporary server")
    
    args = parser.parse_args()
    
    # Process the document
    await process_document(
        args.document_path, 
        args.output,
        args.voice,
        args.port
    )


if __name__ == "__main__":
    # Handle keyboard interrupts gracefully
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Process complete") 