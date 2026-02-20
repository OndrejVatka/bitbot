"use client";

import { useEffect, useRef, useState } from "react";
import type { WSMessage } from "@/types";

export function useWebSocket(url: string) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    function connect() {
      // Convert http(s) → ws(s)
      const wsUrl = url.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"));

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => setIsConnected(true);

      ws.onclose = () => {
        setIsConnected(false);
        // Reconnect after 3s
        reconnectRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();

      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(event.data) as WSMessage;
          setLastMessage(msg);
        } catch {
          // Ignore malformed messages
        }
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [url]);

  return { isConnected, lastMessage };
}
