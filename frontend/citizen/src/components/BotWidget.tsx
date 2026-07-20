import { useState, useRef, useEffect } from 'react';
import { useChatStore } from '../store/chatStore';
import { useSendBotMessage } from '../api/bot';

export default function BotWidget() {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { isOpen, messages, sessionId, toggleOpen, addMessage, setSessionId } = useChatStore();
  const sendMessage = useSendBotMessage();

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isOpen]);

  const handleSend = async () => {
    if (!input.trim() || sendMessage.isPending) return;
    const userText = input.trim();
    setInput('');

    // Add user message immediately (optimistic)
    addMessage({ role: 'user', content: userText, timestamp: new Date().toISOString() });

    sendMessage.mutate(
      { message: userText, session_id: sessionId ?? undefined },
      {
        onSuccess: (data: any) => {
          if (!sessionId && data.session_id) {
            setSessionId(data.session_id);
          }
          addMessage({
            role: 'bot',
            content: data.response,
            timestamp: new Date().toISOString(),
            riskTier: data.risk_assessment?.risk_tier,
          });
        },
        onError: () => {
          addMessage({
            role: 'bot',
            content: 'Sorry, I am having trouble connecting. Please try again.',
            timestamp: new Date().toISOString(),
          });
        },
      }
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Floating button */}
      <button
        onClick={toggleOpen}
        className="fixed bottom-6 right-6 w-14 h-14 bg-blue-600 hover:bg-blue-700 rounded-full shadow-lg flex items-center justify-center text-white text-2xl transition-all hover:scale-110 z-50"
        aria-label="Open fraud assistant"
        id="bot-widget-toggle"
      >
        {isOpen ? '✕' : '🛡️'}
      </button>

      {/* Chat window */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 w-80 h-[28rem] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden z-50 border border-gray-200">
          {/* Header */}
          <div className="bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-3 flex items-center gap-3">
            <div className="w-9 h-9 bg-white/20 rounded-full flex items-center justify-center text-lg">🤖</div>
            <div>
              <p className="text-white font-semibold text-sm">Fraud Shield Assistant</p>
              <p className="text-blue-100 text-xs">AI-powered • 12 languages</p>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-50">
            {messages.length === 0 && (
              <div className="text-center text-gray-400 text-sm py-6">
                <p className="text-2xl mb-2">👋</p>
                <p>Hello! I can help you report cyber fraud or answer questions about your case.</p>
              </div>
            )}
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[75%] px-3 py-2 rounded-2xl text-sm ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white rounded-br-sm'
                      : 'bg-white text-gray-800 shadow-sm rounded-bl-sm border border-gray-100'
                  }`}
                >
                  {msg.content}
                  {msg.riskTier && (
                    <div className="mt-1 text-xs opacity-75">
                      ⚠️ Risk: {msg.riskTier}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {sendMessage.isPending && (
              <div className="flex justify-start">
                <div className="bg-white px-3 py-2 rounded-2xl shadow-sm border border-gray-100">
                  <div className="flex gap-1 items-center h-4">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-gray-200 bg-white">
            <div className="flex gap-2">
              <input
                id="bot-message-input"
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type your message..."
                className="flex-1 text-sm px-3 py-2 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={sendMessage.isPending}
              />
              <button
                id="bot-send-button"
                onClick={handleSend}
                disabled={!input.trim() || sendMessage.isPending}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white rounded-xl px-3 transition-colors"
                aria-label="Send message"
              >
                ➤
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
