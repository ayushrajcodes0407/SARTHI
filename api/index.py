"""
Vercel Serverless Function entry point for SARTHI AI Business Intelligence Assistant.
Exposes WSGI `app` callable to Vercel Python runtime.
"""
import sys
import os

# Add root directory to sys.path so app modules can be resolved cleanly
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app

# Vercel WSGI entry point
# Exports Flask app instance as `app`
if __name__ == "__main__":
    app.run()
