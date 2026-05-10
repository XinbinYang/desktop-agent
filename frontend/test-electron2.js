console.log('process.type:', process.type);
console.log('process.versions:', JSON.stringify(process.versions, null, 2));
try {
  const electron = require('electron');
  console.log('require electron type:', typeof electron);
  console.log('require electron is array:', Array.isArray(electron));
  if (typeof electron === 'string') {
    console.log('require electron value:', electron);
  }
} catch (e) {
  console.log('require electron error:', e.message);
}
