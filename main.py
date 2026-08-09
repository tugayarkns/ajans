import os
from anthropic import Anthropic
from dotenv import load_dotenv
import json
from datetime import datetime

load_dotenv()

client = Anthropic()

MODEL = "claude-opus-5"


class MultiAgentSystem:
    def __init__(self):
        self.agents = {}
        self.order_log = []
        self.load_agents()
        self.conversation_history = []

    def load_agents(self):
        agents_dir = "agents"
        if not os.path.exists(agents_dir):
            print(f"❌ '{agents_dir}' klasörü bulunamadı!")
            return

        for filename in os.listdir(agents_dir):
            if filename.endswith(".md"):
                agent_name = filename.replace(".md", "").upper()
                try:
                    with open(f"{agents_dir}/{filename}", "r", encoding="utf-8") as f:
                        self.agents[agent_name] = f.read()
                except Exception as e:
                    print(f"⚠️ {filename} yüklenemedi: {e}")

        if self.agents:
            print(f"✅ {len(self.agents)} ajan yüklendi\n")
        else:
            print("⚠️ Hiç ajan dosyası bulunamadı!")

    def process_order(self, order_description):
        order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        print(f"\n{'='*60}")
        print(f"📦 YENİ SİPARİŞ: {order_id}")
        print(f"{'='*60}\n")
        print(f"📝 Sipariş Detayı: {order_description}\n")

        if "MASTER_AGENT" not in self.agents:
            print("❌ Master Agent bulunamadı!")
            return

        system_prompt = self.agents['MASTER_AGENT']

        user_message = f"""
## YENİ SİPARİŞ İŞLEMİ

**Sipariş ID:** {order_id}
**Müşteri Talebi:** {order_description}

Lütfen bu siparişi işle ve sırasıyla:
1. Ne yapacağını anlatıcaksın
2. Hangi ajanları çağıracağını söyleyeceksin
3. Her adımın sonuçlarını raporlayacaksın

Başla!
"""

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )

            result = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            print("🤖 MASTER AGENT YANITI:\n")
            print(result)
            print("\n" + "="*60 + "\n")

            self.order_log.append({
                "order_id": order_id,
                "description": order_description,
                "response": result,
                "timestamp": datetime.now().isoformat()
            })

            return result

        except Exception as e:
            print(f"❌ Hata: {e}")
            return None

    def call_specific_agent(self, agent_name, task):
        agent_name = agent_name.upper()

        if agent_name not in self.agents:
            print(f"❌ '{agent_name}' ajanı bulunamadı!")
            return None

        print(f"\n🤖 {agent_name} çağrılıyor...\n")

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1000,
                system=self.agents[agent_name],
                messages=[{"role": "user", "content": task}]
            )

            result = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            print(f"✅ {agent_name} Yanıt:\n{result}\n")
            return result

        except Exception as e:
            print(f"❌ Hata: {e}")
            return None

    def show_logs(self):
        if not self.order_log:
            print("\n📭 Henüz işlenen sipariş yok\n")
            return

        print(f"\n📋 YAPILAN SİPARİŞLER ({len(self.order_log)}):\n")
        for i, order in enumerate(self.order_log, 1):
            print(f"{i}. {order['order_id']} - {order['description']}")
            print(f"   Zaman: {order['timestamp']}\n")


def main():
    system = MultiAgentSystem()

    print("\n" + "="*60)
    print("🚀 MULTI-AGENT SİPARİŞ YÖNETİM SİSTEMİ")
    print("="*60)
    print("\n📌 Komutlar:")
    print("  1. Yeni sipariş gir (Örn: 'Müşteri Ahmet, iPhone case, 2 adet')")
    print("  2. 'ajan ORDER_AGENT' şeklinde spesifik ajan çağır")
    print("  3. 'loglar' yazarak tüm siparişleri göster")
    print("  4. 'çık' yazarak programı kapat\n")

    while True:
        try:
            user_input = input("📝 Komut girin: ").strip()

            if not user_input:
                continue

            if user_input.lower() == "çık":
                print("\n👋 Sistem kapatıldı. Hoşça kalın!\n")
                break

            elif user_input.lower() == "loglar":
                system.show_logs()

            elif user_input.lower().startswith("ajan "):
                agent_name = user_input[5:].strip()
                task = input("📝 Görevi yazın: ").strip()
                if task:
                    system.call_specific_agent(agent_name, task)

            else:
                system.process_order(user_input)

        except KeyboardInterrupt:
            print("\n\n👋 Program durduruldu\n")
            break
        except Exception as e:
            print(f"❌ Hata: {e}\n")


if __name__ == "__main__":
    main()
