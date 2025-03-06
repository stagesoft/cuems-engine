from cuemsengine.cuems_deploy.CuemsDeploy import CuemsDeploy


deployer = CuemsDeploy(library_path='/opt/test')

if deployer.sync('/opt/cuems_library/files.tmp'):
    print("sync ok!")
else:
    print(deployer.errors)
