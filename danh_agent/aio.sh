docker compose up -d
cd agent
docker compose up -d
cd ..
cd Asterisk_docs
python main.py
cd ..
cp -r ./test_env_template ./test_env
chmod +x ./test_env/setup_tool_server.sh
sudo ./test_env/setup_tool_server.sh
cd agent
python main.py