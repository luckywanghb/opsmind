# OpsMind Product Baseline — V0.1

OpsMind is a synthetic manufacturing IT operations Agent designed for education and portfolio demonstration while preserving production-shaped architecture.

## Product principles

- All enterprise data is synthetic.
- Business logic should resemble real enterprise operations.
- The first release is a single Agent, not a multi-Agent product.
- V0.1 is read-only.
- The Agent should reason with models and act through typed tools.
- The system should expose enough traces and evals to explain why the Agent acted as it did.

## Golden Cases

- C01 operation guidance
- C03 missing access permission
- C05 normal work-order wait
- C06 validation failure
- C09 HTTP 500
- C10 broad outage
- C11 privileged change request
- C12 continued unresolved case

## V0.1 non-goals

- real company data;
- production write operations;
- autonomous permission modification;
- Kubernetes;
- multi-Agent business orchestration;
- MCP/A2A unless later justified;
- complete simulation of a manufacturing enterprise.
