import sys
import io

# Fix encoding for Hebrew/Arabic on Linux servers
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app import create_app

application = create_app()

if __name__ == '__main__':
    application.run()
