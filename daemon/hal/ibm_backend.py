from qiskit import QuantumCircuit, transpile
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime import SamplerV2 as Sampler

from .base import QuantumBackend


class IBMBackend(QuantumBackend):
    """Dispatches circuits to IBM Quantum over the network via qiskit-ibm-runtime.

    Credentials must already be saved locally (QiskitRuntimeService.save_account),
    not passed here - this class never touches a token directly.
    """

    def __init__(self, backend_name: str | None = None):
        self._service = QiskitRuntimeService()
        self._backend = (
            self._service.backend(backend_name)
            if backend_name
            else self._service.least_busy(operational=True, simulator=False)
        )
        self.name = self._backend.name
        self.max_qubits = self._backend.num_qubits

    def execute(self, qasm: str, shots: int) -> dict:
        circuit = QuantumCircuit.from_qasm_str(qasm)
        compiled = transpile(circuit, self._backend)

        sampler = Sampler(mode=self._backend)
        job = sampler.run([compiled], shots=shots)
        result = job.result()[0]

        creg_name = compiled.cregs[0].name
        return getattr(result.data, creg_name).get_counts()
