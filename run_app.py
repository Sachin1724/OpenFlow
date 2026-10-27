"""
OpenFlow - Standalone Application Launcher
Created by Sachidananda
"""
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from openflow.main import main

if __name__ == "__main__":
    main()
