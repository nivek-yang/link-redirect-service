# redirect-service/messaging.py
import json
import os

import pika


def publish_click_event(slug: str):
    RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "localhost")
    try:
        # 建立與 RabbitMQ 伺服器的連線
        # pika.BlockingConnection: 建立一個同步的、阻塞式的連線。
        # 這裡使用阻塞式連線是因為發送訊息是一個快速操作，且我們希望確保訊息被發送。
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST)
        )
        # 通道是連線內部的邏輯路徑，用於發送和接收訊息。
        # 一個連線可以有多個通道，這樣可以提高效率。
        channel = connection.channel()
        # 宣告一個佇列 (Queue)
        channel.queue_declare(
            queue="link_clicks", durable=True
        )  # durable=True for persistence

        message = {"slug": slug}
        # 發布訊息
        # 使用預設的交換器 (default exchange)
        # 預設交換器會根據 routing_key 將訊息直接路由到同名的佇列。
        # routing_key='link_clicks': 訊息將被路由到名為 'link_clicks' 的佇列。
        channel.basic_publish(
            exchange="",
            routing_key="link_clicks",
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent  # 即使 RabbitMQ 伺服器在訊息被消費者處理前重啟，這條訊息也不會丟失，它會被寫入磁碟
            ),
        )
        print(f"Published click event for slug: {slug}")
        connection.close()
    except Exception as e:
        print(f"Failed to publish click event for slug {slug}: {e}")
        # 在實際生產環境中，這裡應該有更健壯的錯誤處理機制，例如重試、記錄到日誌系統、或發送到死信佇列 (Dead-Letter Queue)。

    finally:
        # 8. 關閉連線
        # 無論成功或失敗，都嘗試關閉與 RabbitMQ 的連線。
        if "connection" in locals() and connection.is_open:
            connection.close()
