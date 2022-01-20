1. pip install -r requirements.txt
2. Vytvořte aplikaci na https://discord.com/developers/applications
3. Přejděte do Bot a klikněte na Add Bot
4. Odtud získáte token, který pak vložíte do settings.py
5. Zpátky na General Information, tady získáte client id. To doplňte do této adresy:

        https://discord.com/api/oauth2/authorize?client_id=<sem doplňte client id>&permissions=66560&scope=bot

    Tato adresa slouží k přidání bota na server.

6. Upravte settings.py (zkopírováním settings.py.example) a nastavte si kanály a adresáře.

**Additional steps for running the bot locally:**

7. Create "state" directory in project and put DB in there
8. Create "out" directory in project and put urls.csv in there
9. Create "out/tmp" directory in project
10. Create "out/attachments" directory in project
