# 准备上传GitHub

## 包含内容

根目录的3个Python程序、3个Windows启动入口、README、requirements、.gitignore、docs和tests。`work/`、`outputs/`、`logs/`、虚拟环境及缓存不进入仓库；原始本地数据不会因下列git add命令被加入。

## 上传前验证

```powershell
py -3.12 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
git status --short
```

远程仓库为公开仓库：[Mubea-202611.12-Cyclinder-test](https://github.com/wangbo20261102/Mubea-202611.12-Cyclinder-test)。当前尚未指定许可证。以下命令用于后续维护；首次取回项目可直接使用git clone。

## 提交与推送

项目目录已有本地Git仓库；从ZIP解压到新目录时先执行`git init`。

```powershell
git add README.md .gitignore requirements.txt mcea_read.py mcea_home.py mcea_direction_test.py *.cmd docs tests
git diff --cached --stat
git diff --cached
git commit -m "Add MCEA serial diagnostics and supervised motion tests"
git branch -M main
```

首次配置远程地址时使用：

```powershell
git remote add origin https://github.com/wangbo20261102/Mubea-202611.12-Cyclinder-test.git
git push -u origin main
```

如果已经配置origin，先用`git remote -v`核对，不重复添加，也不使用强制推送。不要把访问令牌写进程序、README或远程URL。项目未提交任何许可证文本，选择开源许可后再添加LICENSE。
