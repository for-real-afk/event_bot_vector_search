#!/bin/bash
# Run this once on your EC2 instance to deploy the search service.
# Usage: bash deploy.sh

set -e

echo "── Cloning / pulling latest code ──────────────────────────"
# If first time:
# git clone https://github.com/your-repo/event-search-service.git
# cd event-search-service
# If updating:
git pull

echo "── Creating virtualenv ─────────────────────────────────────"
python3 -m venv venv
source venv/bin/activate

echo "── Installing dependencies ─────────────────────────────────"
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "── Pre-caching embedding model ─────────────────────────────"
python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5'); print('Model ready.')"

echo "── Setting up .env ─────────────────────────────────────────"
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  !! Edit .env and add your PINECONE_API_KEY, then re-run."
    echo ""
    exit 1
fi

echo "── Installing systemd service ──────────────────────────────"
sudo cp event-search.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable event-search
sudo systemctl restart event-search

echo ""
echo "── Done. Service status: ───────────────────────────────────"
sudo systemctl status event-search --no-pager

echo ""
echo "  Service running at http://$(curl -s ifconfig.me):8001"
echo "  Swagger UI:        http://$(curl -s ifconfig.me):8001/docs"
echo ""
echo "  Logs: sudo journalctl -u event-search -f"
