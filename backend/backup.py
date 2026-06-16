import json
import os
import datetime

class DataBackup:
    def __init__(self, backup_dir="./backups"):
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_backup(self, data, filename_prefix="data"):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = os.path.join(self.backup_dir, f"{filename_prefix}_{timestamp}.json")
        try:
            with open(backup_filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"Backup criado com sucesso: {backup_filename}")
            return backup_filename
        except IOError as e:
            print(f"Erro ao criar backup: {e}")
            return None

    def load_latest_backup(self, filename_prefix="data"):
        backup_files = [f for f in os.listdir(self.backup_dir) if f.startswith(filename_prefix) and f.endswith(".json")]
        if not backup_files:
            print("Nenhum arquivo de backup encontrado.")
            return None
        
        backup_files.sort(reverse=True) # Pega o mais recente
        latest_backup_file = os.path.join(self.backup_dir, backup_files[0])
        
        try:
            with open(latest_backup_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"Backup carregado com sucesso: {latest_backup_file}")
            return data
        except IOError as e:
            print(f"Erro ao carregar backup: {e}")
            return None

# Exemplo de uso (será integrado ao bot Discord ou agendado)
if __name__ == "__main__":
    backup_manager = DataBackup()

    # Exemplo de dados para backup
    sample_data = {
        "products": [
            {"id": 1, "name": "Curso Premium", "price": 99.90, "stock": "unlimited"},
            {"id": 2, "name": "Ebook Completo", "price": 49.90, "stock": "unlimited"}
        ],
        "sales": [
            {"order_id": "#001234", "product_id": 1, "amount": 99.90, "date": "2026-06-15"}
        ]
    }

    # Criar um backup
    # backup_manager.create_backup(sample_data, "vendabot_data")

    # Carregar o backup mais recente
    # loaded_data = backup_manager.load_latest_backup("vendabot_data")
    # if loaded_data:
    #     print("Dados do backup:")
    #     print(json.dumps(loaded_data, indent=4))
