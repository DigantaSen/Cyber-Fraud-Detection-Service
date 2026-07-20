import { useMutation, useQuery } from '@tanstack/react-query';
import apiClient from './client';

export const useSendBotMessage = () =>
  useMutation({
    mutationFn: async (payload: { message: string; session_id?: string }) => {
      const res = await apiClient.post('/api/v1/citizen/bot/message', payload);
      return res.data.data;
    },
  });

export const useBotSession = (sessionId: string | null) =>
  useQuery({
    queryKey: ['bot-session', sessionId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/citizen/bot/session/${sessionId}`);
      return res.data.data;
    },
    enabled: !!sessionId,
  });
