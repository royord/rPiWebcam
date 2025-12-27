<?php
    //echo $visitCounter;
    if(!isset($_SESSION['count'])){
        // Open file and read in counter value

        // Counter not yet set;
        $_SESSION['count'] = $visitCounter;

        $counter = $_SESSION['count']++; 
        // Echo Test Var
        // echo "Setting Counter";
        // 
    }
    else {
        $_SESSION['count'] = $visitCounter;
        $counter = $_SESSION['count'];
    };
    $counter = $_SESSION['count']; 
    $counter = (int)$counter;
    
    // Used for testing
    //session_destroy();
    if(!file_exists($counterFile)){
        echo "file needs to be created for counting visitors.<br>";
        $myFile = fopen($counterFile,'w');
    };
    if(!is_writeable($counterFile)){
        echo "file for counting visitors is NOT writeable.<br>";
    }
    if(!is_readable($counterFile)){
        echo "file for counting visitors is NOT readable<br>";
    }
    if(!is_file($counterFile)){
        echo "something is wrong visit counter file $counterFile.<br>";
    }
    if(
        !(
            file_exists($counterFile)
            //&& is_writeable($counterFile)
            && is_readable($counterFile)
            && is_file($counterFile)
        )
    )
    {
        echo "file needs to be made";
        $myfile = fopen($counterFile, "r");
    }
    else if(
        file_exists($counterFile)
            && is_writeable($counterFile)
            && is_readable($counterFile) && is_file($counterFile)
    ){
        $visitCounter = $_SESSION['count'];
        $var_str = var_export($counter, true);
        $var = "<?php\n\$visitCounter = $var_str;\n?>";
        file_put_contents($counterFile, $var);
        //Retrieving it again:
    }
    else if(file_exists($counterFile)){
        include $counterFile;
        echo $text;
    }
?>