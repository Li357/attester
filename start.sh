sudo pip3 install -r requirements.txt

sudo cp attest.service /etc/systemd/system
sudo cp attest.timer /etc/systemd/system
sudo systemctl enable --now attest.timer