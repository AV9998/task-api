pipeline {
    agent { label 'docker' }

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }

    environment {
        IMAGE_TAG = "task-api:${BUILD_NUMBER}"
    }

    stages {

        stage('Build') {
            steps {
                sh '''
                    mkdir -p artifacts
                    docker build -t "$IMAGE_TAG" .
                    docker save "$IMAGE_TAG" -o artifacts/task-api.tar
                '''

                archiveArtifacts artifacts: 'artifacts/task-api.tar',
                                 fingerprint: true
            }
        }

        stage('Test') {
    steps {
        sh '''
            python3 -m pip install --user unittest-xml-reporting coverage

            rm -rf test-results
            mkdir -p test-results

            python3 -m coverage erase

            python3 -m coverage run --source=app \
                -m xmlrunner discover \
                -s tests \
                -v \
                -o test-results

            python3 -m coverage xml -o coverage.xml
            python3 -m coverage report
        '''
    }

    post {
        always {
            junit testResults: 'test-results/*.xml',
                  allowEmptyResults: false

            archiveArtifacts artifacts: 'coverage.xml',
                             allowEmptyArchive: true
        }

        success {
            echo 'TEST GATE: PASSED'
        }
    }
}

        stage('Code Quality') {
    steps {
        sh '''
            python3 -m venv .ci-venv
            .ci-venv/bin/pip install ruff radon
            .ci-venv/bin/ruff check app tests scripts
            .ci-venv/bin/radon cc app -s
        '''

        script {
            def scannerHome = tool 'SonarScanner'

            withSonarQubeEnv('SonarQube') {
                sh "${scannerHome}/bin/sonar-scanner"
            }
        }
    }
}

stage('Quality Gate') {
    steps {
        timeout(time: 5, unit: 'MINUTES') {
            waitForQualityGate abortPipeline: true
        }
    }
}

        stage('Security') {
            steps {
                sh '''
                    .ci-venv/bin/pip install bandit
                    .ci-venv/bin/bandit -r app -ll
                '''

                sh '''
                    docker run --rm \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        aquasec/trivy:0.65.0 \
                        image \
                        --exit-code 1 \
                        --severity HIGH,CRITICAL \
                        --ignore-unfixed \
                        "$IMAGE_TAG"
                '''
            }
        }

        stage('Deploy') {
            steps {
                withCredentials([
                    string(
                        credentialsId: 'task-api-token-secret',
                        variable: 'TOKEN_SECRET'
                    )
                ]) {
                    sh '''
                        APP_IMAGE="$IMAGE_TAG" \
                        APP_PORT=18080 \
                        docker compose \
                            -p task-staging \
                            -f compose.yml \
                            up -d --wait
                    '''

                    sh '''
                        BASE_URL=http://127.0.0.1:18080 \
                        python3 scripts/smoke.py
                    '''
                }
            }
        }

        stage('Release') {
            when {
                branch 'main'
            }

            steps {
                input message: 'Promote this tested image to production?'

                withCredentials([
                    string(
                        credentialsId: 'task-api-token-secret',
                        variable: 'TOKEN_SECRET'
                    )
                ]) {
                    sh '''
                        APP_IMAGE="$IMAGE_TAG" \
                        APP_PORT=18081 \
                        docker compose \
                            -p task-production \
                            -f compose.yml \
                            up -d --wait
                    '''

                    sh '''
                        BASE_URL=http://127.0.0.1:18081 \
                        python3 scripts/smoke.py
                    '''
                    withCredentials([
    usernamePassword(
        credentialsId: 'github-push',
        usernameVariable: 'GIT_USERNAME',
        passwordVariable: 'GIT_TOKEN'
    )
]) {
    sh '''
        TAG="v1.0.${BUILD_NUMBER}"

        git config user.name "Jenkins"
        git config user.email "jenkins@localhost"

        git tag -a "$TAG" -m "Release $TAG"

        git push \
          "https://${GIT_USERNAME}:${GIT_TOKEN}@github.com/AV9998/task-api.git" \
          "$TAG"

        echo "RELEASE TAG PUSHED: $TAG"
    '''
}
                }
            }
        }

        stage('Monitoring and Alerting') {
            when {
                branch 'main'
            }

            steps {
                withCredentials([
                    string(
                        credentialsId: 'task-api-token-secret',
                        variable: 'TOKEN_SECRET'
                    ),
                    string(
                        credentialsId: 'task-alert-gmail-address',
                        variable: 'ALERT_EMAIL'
                    ),
                    string(
                        credentialsId: 'task-alert-gmail-app-password',
                        variable: 'GMAIL_APP_PASSWORD'
                    )
                ]) {
                    sh '''
                        APP_IMAGE="$IMAGE_TAG" \
                        APP_PORT=18081 \
                        docker compose \
                            -p task-production \
                            -f compose.yml \
                            -f compose.monitoring.yml \
                            up -d --wait
                    '''

                    sh '''
                        curl --fail --silent \
                            http://127.0.0.1:9090/-/healthy

                        curl --fail --silent \
                            http://127.0.0.1:9090/api/v1/rules \
                            -o artifacts/prometheus-rules.json

                        python3 scripts/check_rules.py \
                            artifacts/prometheus-rules.json
                    '''
sh '''
    # Wait for Prometheus to scrape the production API
    sleep 20

    curl --fail --silent \
      'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22task-api%22%7D' \
      -o artifacts/prometheus-target.json

    python3 - <<'PY'
import json

with open("artifacts/prometheus-target.json") as f:
    data = json.load(f)

results = data["data"]["result"]

if not results:
    raise SystemExit("PRODUCTION TARGET CHECK FAILED: task-api target not found")

if results[0]["value"][1] != "1":
    raise SystemExit("PRODUCTION TARGET CHECK FAILED: task-api is DOWN")

print("PRODUCTION TARGET CHECK: UP")
PY
'''   
                sh '''
    echo "INCIDENT TEST: stopping production API"

    # Stop only the production API container.
    docker stop task-production-api-1

    # Always restore the API, even if the alert check fails.
    trap 'docker start task-production-api-1 >/dev/null 2>&1 || true' EXIT

    echo "Waiting for TaskApiDown to enter FIRING state..."

    # Rule requires 1 minute; allow enough time for scraping/evaluation.
    sleep 90

    curl --fail --silent \
      http://127.0.0.1:9090/api/v1/alerts \
      -o artifacts/prometheus-alerts.json

    python3 - <<'PY'
import json

with open("artifacts/prometheus-alerts.json") as f:
    data = json.load(f)

alerts = data["data"]["alerts"]

firing = [
    alert for alert in alerts
    if alert["labels"].get("alertname") == "TaskApiDown"
    and alert["state"] == "firing"
]

if not firing:
    raise SystemExit(
        "INCIDENT TEST FAILED: TaskApiDown did not reach FIRING state"
    )

print("INCIDENT TEST: TaskApiDown is FIRING")
PY

    echo "Restoring production API"
    docker start task-production-api-1

    # Disable EXIT restoration because we restored it explicitly.
    trap - EXIT

    echo "Waiting for production API to recover..."
    sleep 20

    curl --fail --silent http://127.0.0.1:18081/health

    echo
    echo "INCIDENT TEST: production API restored successfully"
'''}
            }
        }
    }
}
