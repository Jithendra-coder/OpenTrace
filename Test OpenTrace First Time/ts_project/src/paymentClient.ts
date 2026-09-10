import axios from 'axios';

export interface PaymentRequest {
  order_id: string;
  amount: number;
}

export async function processPayment(data: PaymentRequest) {
  // Directly calls POST /payments endpoint affected by field rename
  const response = await axios.post('/payments', {
    order_id: data.order_id,
    amount: data.amount,
  });
  return response.data;
}
