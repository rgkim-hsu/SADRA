# ADR 생성 결과 (LLM: qwen)

**이미지:** RPT-25.png
**생성일시:** 2026-04-22 13:54:37
**소요 시간:** 52.76초 (0.88분)

---

# 🏗️ 아키텍처 분석 보고서

## 📋 ADR (Architecture Decision Record)

### ADR-001: 상태 전이 기반 명령 우선순위 및 중재 로직 채택

| 항목 | 내용 |
|------|------|
| **상황 (Context)** | 제공된 개념도 (State Diagram) 는 명령의 수명주기를 'NEW'에서 시작하여 'WORKING' 상태를 거쳐 완료되는 구조를 보여줍니다. <br>1. **명령 충돌 상황:** 'WORKING' 중 새로운 명령이나 'AUTO CONTROL' 신호가 들어오면 현재 작업이 'IGNORED'됩니다.<br>2. **중단 상황:** 'STOPPING BY A-SENSOR' 또는 'STOPPING BY STOP COMMAND'로 인해 작업이 강제 종료됩니다.<br>이 시스템은 IoT 환경에서 명령의 신뢰성 처리와 안전 우선 원칙 (Safety First) 을 준수해야 합니다. |
| **결정 (Decision)** | **"명령 우선순위 계층 구조 (Command Priority Hierarchy) 구현"**<br>시스템은 다음과 같은 우선순위 로직을 상태 전이 테이블 (State Transition Table) 로 정의합니다:<br>1. **가장 높은 우선순위:** Auto Control 신호 (비상 상황/자동 제어). 이는 시스템 상태를 즉시 변경하거나 무시합니다.<br>2. **높은 우선순위:** 새 명령 (New Command). 이는 현재 실행 중인 명령을 대체 (Preempt) 합니다.<br>3. **최하위 우선순위:** 현재 실행 중인 명령 (Sent/Working). 이는 위의 두 가지 신호에 의해 중단되거나 무시됩니다. |
| **근거 (Rationale)** | <ul><li>**안전성 (Safety):** IoT 기기, 특히 스마트팜이나 산업 제어 장비에서는 안전이 최우선입니다. 자동 제어 (Auto Control) 신호가 들어오는 경우 (예: 센서 이상, 위험 상황), 수동 명령을 무시하는 것이 필수적입니다.</li><li>**일관성 (Consistency):** 동시에 수행될 수 없는 작업들이 충돌할 때, 시스템이 명확한 행동을 보장하려면 결정론적 (Deterministic)인 우선순위 로직이 필요합니다.</li><li>**확장성:** 상태 전이 (State Transition) 방식은 시스템 로직을 명확하게 정의하여 유지보수를 용이하게 합니다.</li></ul> |
| **결과 (Consequences)** | **긍정적:** 복잡한 명령 충돌 상황을 명확히 관리하며, 시스템의 예측 가능성을 높입니다.<br>**부정적/제한점:** 우선순위가 낮은 명령이 무시될 수 있으며, 이를 로깅 (Logging) 하거나 사용자에게 알리는 추가 로그 관리 로직이 필요합니다. |
| **트레이드오프 (Trade-offs)** | <ul><li>**장점:** 복잡한 상황에서도 시스템이 정적 (Determinate) 인 상태를 유지합니다.</li><li>**단점:** 모든 충돌을 'Ignore'로 처리하기 때문에, 실제 실행되지 않는 명령에 대한 피드백이 부족할 수 있습니다 (해결책: ignored 이벤트 로그 생성).</li></ul> |

---

## ⚠️ 잠재적 위험 분석

### 1. 명령 무시 (Ignore) 로 인한 시스템 동작 누락
- **설명:** 현재 'WORKING' 중인 작업에 대해 새 명령이나 Auto Control 신호가 오면 'IGNORED BY...' 상태로 이동합니다. 이 과정에서 중요한 설정값이나 명령이 실제로 실행되지 않았으나 시스템이 이를 인지하지 못하는 경우, 시스템 상태가 실제 물리적 상태와 불일치할 수 있습니다.
- **심각도:** 🔴 High
- **발생 가능성:** 🔴 High
- **대응 방안:** 
    - `IGNORED` 이벤트 발생 시 중앙 관리자 서버 (Management Server) 에 '이벤트 로그'를 반드시 기록해야 합니다.
    - 관리자 UI 에서 "미처리 명령이 N 개 존재합니다"라는 알림창을 띄워 운영자에게 경고해야 합니다.

### 2. 'A-SENSOR' 단일 실패점 (Single Point of Failure) 의존성
- **설명:** 'WORKING' 상태에서 'STOPPING BY A-SENSOR' 로 전환되는데, 이는 특정 센서 (A-SENSOR) 가 작동하는 것을 전제로 합니다. 해당 센서가 고장나거나 교란되면 (False Positive), 유효한 작업이 갑자기 중단되어 'FINISHED BY A-SENSOR'가 됩니다. 이는 실제 작업이 끝난 것이 아닙니다.
- **심각도:** 🟠 Medium
- **발생 가능성:** 🟠 Medium
- **대응 방안:** 
    - 센서 감지 신호를 최소 2 개 이상 이중화하여 처리하거나, 임계값 (Threshold) 을 엄격히 설정하여 오감지 (False Positive) 를 줄여야 합니다.
    - 센서 교정이 필요할 때의 'Maintenance Mode'를 정의하여, 센서 오류가 발생해도 작업이 무리하게 중단되지 않도록 로직을 보완해야 합니다.

### 3. 명령 폭주 (Command Storm) 상황에서의 상태 마신 (State Locking)
- **설명:** 매우 짧은 시간 안에 수많은 'NEW' 명령이나 'STOP COMMAND'가 집중적으로 들어오면 (예: 네트워크 불안정, 공격 시나리오), 'WORKING' 상태가 반복되거나 'WAITING' 큐가 붕괴될 수 있습니다. 상태 전이 로직의 오버헤드로 인해 시스템 응답이 느려지거나 멈출 수 있습니다.
- **심각도:** 🟠 Medium
- **발생 가능성:** 🟡 Medium
- **대응 방안:** 
    - 명령 수신기는 'Rate Limiter'를 적용하여 일정 시간 내의 과도한 요청을 거절하거나 큐잉해야 합니다.
    - 상태 전이 도표에 'TIMEOUT' 상태를 추가하여, 'WORKING' 상태가 지나치게 길어지거나 신호가 없으면 자동으로 'ERROR' 또는 'RESET' 상태로 강제 전환하도록 설계해야 합니다.

### 4. 'STOP COMMAND' 의 보안 취약성 (Unauthorized Termination)
- **설명:** 'FINISHED BY STOP COMMAND' 로직이 존재합니다. 만약 이 'STOP COMMAND'를 악의적인 공격자가 보낸다면, 시스템이 중요한 작업 (예: 물리적 장치 작동, 데이터 수집) 을 중단시킬 수 있습니다. 이는 'STOPPING BY A-SENSOR'만큼 안전성이 보장되지 않을 수 있습니다.
- **심각도:** 🔴 High
- **발생 가능성:** 🟡 Medium
- **대응 방안:** 
    - 'STOP COMMAND'는 반드시 인증된 토큰 (Token) 또는 권한을 가진 소스 IP 만 허용해야 합니다.
    - 아키텍처 문서 (ETSI EN 303 645 등) 에 명시된 대로 암호화 및 접근 제어 (Authentication/Authorization) 를 강화해야 합니다.

### 5. 'AUTO CONTROL' 의 오동작에 따른 오작동 연쇄
- **설명:** 'IGNORED BY AUTO CONTROL' 로직은 자동 제어 장치가 우선권을 가집니다. 만약 이 'AUTO CONTROL' 장치가 오작동하여 항상 'Ignore' 신호를 보낸다면, 사용자가 모든 명령을 입력할 수 없고 시스템은 사실상 가동 정지 상태가 될 수 있습니다.
- **심각도:** 🔴 High
- **발동 가능성:** 🟡 Medium
- **대응 방안:** 
    - 'AUTO CONTROL' 상태 자체를 모니터링해야 합니다.
    - 'AUTO CONTROL'이 비정상 상태일 때는 경보를 발생시키고, 수동으로 시스템이 재설정될 수 있는 'Force Disable' 기능을 제공할 수 있도록 해야 합니다.