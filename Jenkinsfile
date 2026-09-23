pipeline {
  agent { label 'docker' }
  options { timestamps(); disableConcurrentBuilds(); timeout(time: 45, unit: 'MINUTES') }
  environment {
    IMAGE_TAG = "task-api:${BUILD_NUMBER}"
  }
  stages {
    stage('Build') {
      steps {
        sh 'mkdir -p artifacts && docker build -t "$IMAGE_TAG" . && docker save "$IMAGE_TAG" -o artifacts/task-api.tar'
        archiveArtifacts artifacts: 'artifacts/task-api.tar', fingerprint: true
      }
    }
    stage('Test') {
      steps {
        sh 'python3 -m unittest discover -s tests -v'
      }
    }
    stage('Code Quality') {
      steps {
        sh 'python3 -m venv .ci-venv && .ci-venv/bin/pip install ruff radon && .ci-venv/bin/ruff check app tests scripts && .ci-venv/bin/radon cc app -s'
      }
    }
    stage('Security') {
      steps {
        sh '.ci-venv/bin/pip install bandit && .ci-venv/bin/bandit -r app -ll'
        sh 'docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.65.0 image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed "$IMAGE_TAG"'
      }
    }
    stage('Deploy') {
      steps {
        withCredentials([string(credentialsId: 'task-api-token-secret', variable: 'TOKEN_SECRET')]) {
          sh 'APP_IMAGE="$IMAGE_TAG" APP_PORT=18080 docker compose -p task-staging -f compose.yml up -d --wait'
          sh 'BASE_URL=http://127.0.0.1:18080 python3 scripts/smoke.py'
        }
      }
    }
    stage('Release') {
      when { branch 'main' }
      steps {
        input message: 'Promote this tested image to production?'
        withCredentials([string(credentialsId: 'task-api-token-secret', variable: 'TOKEN_SECRET')]) {
          sh 'APP_IMAGE="$IMAGE_TAG" APP_PORT=18081 docker compose -p task-production -f compose.yml up -d --wait'
          sh 'BASE_URL=http://127.0.0.1:18081 python3 scripts/smoke.py'
        }
      }
    }
    stage('Monitoring and Alerting') {
      when { branch 'main' }
      steps {
        withCredentials([
          string(credentialsId: 'task-api-token-secret', variable: 'TOKEN_SECRET'),
          string(credentialsId: 'task-alert-gmail-address', variable: 'ALERT_EMAIL'),
          string(credentialsId: 'task-alert-gmail-app-password', variable: 'GMAIL_APP_PASSWORD')
        ]) {
          sh 'APP_IMAGE="$IMAGE_TAG" APP_PORT=18081 docker compose -p task-production -f compose.yml -f compose.monitoring.yml up -d --wait'
          sh 'curl --fail --silent http://127.0.0.1:9090/-/healthy && curl --fail --silent http://127.0.0.1:9090/api/v1/rules | python3 -c "import json,sys; d=json.load(sys.stdin); assert d[\"status\"] == \"success\" and any(g[\"rules\"] for g in d[\"data\"][\"groups\"])"'
        }
      }
    }
  }
}
