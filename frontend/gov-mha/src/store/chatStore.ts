import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface Message {
  id: string;
  role: 'user' | 'bot';
  content: string;
  timestamp: string;
  riskTier?: string;
}

interface ChatState {
  sessionId: string | null;
  messages: Message[];
  isOpen: boolean;
  detectedLanguage: string;
  setSessionId: (id: string) => void;
  addMessage: (msg: Omit<Message, 'id'>) => void;
  toggleOpen: () => void;
  clearSession: () => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      sessionId: null,
      messages: [],
      isOpen: false,
      detectedLanguage: 'en',
      setSessionId: (id) => set({ sessionId: id }),
      addMessage: (msg) =>
        set((state) => ({
          messages: [...state.messages, { ...msg, id: crypto.randomUUID() }],
        })),
      toggleOpen: () => set((state) => ({ isOpen: !state.isOpen })),
      clearSession: () => set({ sessionId: null, messages: [], detectedLanguage: 'en' }),
    }),
    { name: 'citizen-chat' }
  )
);
