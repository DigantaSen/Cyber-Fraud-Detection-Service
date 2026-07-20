import { render, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import BotWidget from '../BotWidget';
import { useChatStore } from '../../store/chatStore';

vi.mock('../../api/bot', () => ({
  useSendBotMessage: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}));

const renderWidget = () => {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <BotWidget />
    </QueryClientProvider>
  );
};

describe('BotWidget', () => {
  beforeEach(() => {
    useChatStore.setState({ isOpen: false, messages: [], sessionId: null });
  });

  it('shows floating toggle button', () => {
    renderWidget();
    const btn = document.getElementById('bot-widget-toggle');
    expect(btn).toBeInTheDocument();
  });

  it('chat window is hidden initially', () => {
    renderWidget();
    // Input should not be visible before widget opens
    const input = document.getElementById('bot-message-input');
    expect(input).toBeNull();
  });

  it('opens chat window on button click', () => {
    renderWidget();
    const btn = document.getElementById('bot-widget-toggle')!;
    fireEvent.click(btn);
    const input = document.getElementById('bot-message-input');
    expect(input).toBeInTheDocument();
  });

  it('closes chat window on second button click', () => {
    renderWidget();
    const btn = document.getElementById('bot-widget-toggle')!;
    fireEvent.click(btn);  // open
    fireEvent.click(btn);  // close
    const input = document.getElementById('bot-message-input');
    expect(input).toBeNull();
  });

  it('send button is disabled when input is empty', () => {
    renderWidget();
    const btn = document.getElementById('bot-widget-toggle')!;
    fireEvent.click(btn);
    const sendBtn = document.getElementById('bot-send-button') as HTMLButtonElement;
    expect(sendBtn.disabled).toBe(true);
  });
});
