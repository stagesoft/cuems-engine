from cuems.cuems_deploy.CuemsDeploy import CuemsDeploy


d = CuemsDeploy(library_path='/opt/test')
result = d.sync('/opt/cuems_library/files.tmp')

if result == True:
    print("sync ok!")
else:
    print(result)