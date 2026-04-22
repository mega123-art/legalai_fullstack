"use client";

import { useParams } from "next/navigation";
import ChatView from "@/components/ChatView";

export default function SessionPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  return <ChatView initialSessionId={sessionId} />;
}
