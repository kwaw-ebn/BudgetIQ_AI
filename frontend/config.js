window.BUDGETIQ_API = ['localhost','127.0.0.1'].includes(location.hostname)
  ? 'http://localhost:8000'
  : 'https://budgetiq-api.onrender.com';
