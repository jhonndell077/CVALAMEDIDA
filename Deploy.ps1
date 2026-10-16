$ErrorActionPreference = 'Stop'
$deployMutex = [Threading.Mutex]::new($false, 'Local\CVALAMEDIDA_FIREBASE_DEPLOY')
$deployOwnsMutex = $false
try { $deployOwnsMutex = $deployMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $deployOwnsMutex = $true }
if (-not $deployOwnsMutex) { $deployMutex.Dispose(); throw 'Ya hay un despliegue de CVALAMEDIDA en ejecuci�n. Espera a que termine.' }
Push-Location $PSScriptRoot
try {
    $deployOrigin = git remote get-url origin
    if ($LASTEXITCODE -ne 0 -or $deployOrigin -ne 'https://github.com/jhonndell077/CVALAMEDIDA.git') { throw 'Configura primero el repositorio privado CVALAMEDIDA como origin.' }
    $deployBranch = git branch --show-current
    if ($deployBranch -ne 'main') { throw 'El Deploy sincronizado debe ejecutarse desde main.' }
    git fetch origin main
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar GitHub antes de publicar.' }
    git merge-base --is-ancestor origin/main HEAD
    if ($LASTEXITCODE -ne 0) { throw 'GitHub tiene cambios nuevos. Integra esos cambios con git pull antes de desplegar; no se sobrescribirán.' }
    $releasePython = Join-Path $PSScriptRoot 'venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $releasePython)) { $releasePython = 'python' }
    & $releasePython -m pip_audit --disable-pip --no-deps --strict -r requirements.txt --progress-spinner off
    if ($LASTEXITCODE -ne 0) { throw 'Dependency audit blocked deployment.' }
    & $releasePython scripts/verify_release.py
    if ($LASTEXITCODE -ne 0) { throw 'La verificacion integral bloqueo el despliegue. Revisa tmp/verification.' }
    git add --all
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron preparar los archivos.' }
    python scripts/check_publish.py
    if ($LASTEXITCODE -ne 0) { throw 'La revisión de archivos bloqueó la publicación.' }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 1) {
        git commit -m 'chore: prepare local Firebase deployment [skip ci]'
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo guardar el commit local.' }
    } elseif ($LASTEXITCODE -ne 0) { throw 'No se pudo revisar el estado de Git.' }
    # Publish all functions declared by main.py and both configured Hosting sites.
    & firebase deploy --only 'functions,hosting' --project 'cv-a-la-medida-jhonn' --non-interactive
    if ($LASTEXITCODE -ne 0) { throw "Firebase no completó el despliegue (código $LASTEXITCODE)." }
    git add --all
    python scripts/check_publish.py
    if ($LASTEXITCODE -ne 0) { throw 'Firebase publicó; la sincronización se bloqueó por archivos no permitidos. Corrige y haz push sin repetir el deploy.' }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 1) {
        git commit -m 'chore: sync successful Firebase deploy [skip ci]'
        if ($LASTEXITCODE -ne 0) { throw 'Firebase publicó; no se pudo guardar el resultado en Git.' }
    }
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw 'Firebase publicó, pero GitHub no se sincronizó. Reintenta git push origin main; no repitas el deploy.' }
    Write-Host 'Firebase publicado y GitHub sincronizado. No se inicia otro deploy automático.'
} finally {
    Pop-Location
    $deployMutex.ReleaseMutex()
    $deployMutex.Dispose()
}
